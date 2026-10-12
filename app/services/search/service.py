"""Servicio de búsqueda global del Geoportal.
Permite localizar geometrías (Features) mediante queries espaciales y de texto.

Refactorizado para usar display_name + Full Text Search (FTS) con tsvector.
Corrige: búsqueda por texto (antes buscaba properties->>'name' que no existía),
         búsqueda por coordenadas (ST_DWithin con geography para radio en metros),
         y sugerencias (ahora usando display_name).
"""

import logging
import re
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Patrón para detectar coordenadas: "10.42, -75.51" o "10.42 -75.51"
COORD_REGEX = re.compile(r"^(-?\d{1,3}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)$")

ROUTE_ALIASES = {
    "alimentadora": ["alimentadoras", "aliment", "ali"],
    "troncal": ["troncales", "tronc", "trk"],
    "complementaria": ["complementarias", "comp", "compl"],
    "petroncal": ["petroncales", "petro"],
}

class SearchService:
    """Implementa búsquedas transversales (Geográficas y Alfanuméricas)."""

    def __init__(self, db: AsyncSession, *, public_only: bool = False):
        self.db = db
        self.public_only = public_only

    def normalize_route_query(self, query: str) -> str:
        q = query.lower().strip()
        for canonical, aliases in ROUTE_ALIASES.items():
            for alias in aliases:
                # Usar límites de palabra para evitar reemplazos parciales incorrectos
                pattern = rf"\b{re.escape(alias)}\b"
                if re.search(pattern, q):
                    return re.sub(pattern, canonical, q)
        return q

    async def search(self, query: str) -> dict[str, Any]:
        """Realiza una búsqueda global mediante el motor integrado."""
        query = self.normalize_route_query(query)
        if not query:
            return {"type": "FeatureCollection", "features": []}

        coord_match = COORD_REGEX.match(query)
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("Coordenadas fuera de rango: latitud [-90, 90], longitud [-180, 180]")
            return await self._search_by_coordinates(lat, lon)

        return await self._search_by_text(query)

    async def get_suggestions(self, limit: int = 5) -> list[str]:
        """Obtiene sugerencias automáticas usando display_name."""
        if not 1 <= limit <= 50:
            raise ValueError("El límite de sugerencias debe estar entre 1 y 50")
        # Features con display_name
        feature_stmt = text("""
            SELECT display_name
            FROM (
                SELECT DISTINCT display_name
                FROM layer_features lf
                JOIN layers l ON l.id = lf.layer_id
                WHERE display_name IS NOT NULL
                  AND (NOT :public_only OR l.visibility = 'PUBLIC')
            ) AS distinct_features
            ORDER BY RANDOM()
            LIMIT :limit
        """)
        features = (await self.db.execute(feature_stmt, {
            "limit": limit, "public_only": self.public_only,
        })).scalars().all()

        results = list(dict.fromkeys(str(item) for item in features if item))
        return results[:limit]

    async def _search_by_coordinates(self, lat: float, lon: float) -> dict[str, Any]:
        """Localiza entidades geográficas por proximidad espacial (Radio de 2km).
        
        Usa geography cast para que ST_DWithin trabaje en metros reales,
        y ordena por distancia ascendente.
        """
        stmt = text("""
            SELECT 
                lf.id::text,
                lf.display_name,
                lf.layer_id::text,
                lf.properties,
                ST_AsGeoJSON(lf.geom)::json AS geometry,
                ARRAY[
                    ST_XMin(ST_Envelope(lf.geom)),
                    ST_YMin(ST_Envelope(lf.geom)),
                    ST_XMax(ST_Envelope(lf.geom)),
                    ST_YMax(ST_Envelope(lf.geom))
                ] AS bbox,
                ST_Distance(
                    lf.geom::geography,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                ) AS dist_metros
            FROM layer_features lf
            JOIN layers l ON l.id = lf.layer_id
            WHERE ST_DWithin(
                lf.geom::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                2000
            )
            AND (NOT :public_only OR l.visibility = 'PUBLIC')
            ORDER BY dist_metros ASC
            LIMIT 15
        """)

        result = await self.db.execute(stmt, {
            "lat": lat, "lon": lon, "public_only": self.public_only,
        })
        rows = result.mappings().all()

        features = []
        for r in rows:
            props = dict(r["properties"]) if r["properties"] else {}
            props["display_name"] = r["display_name"]
            props["layer_id"] = r["layer_id"]
            props["source"] = "feature"
            props["bbox"] = r["bbox"]
            dist = r["dist_metros"]
            if dist is not None:
                if dist < 1000:
                    props["distance_label"] = f"{int(dist)} m"
                else:
                    props["distance_label"] = f"{dist/1000:.1f} km"

            features.append({
                "type": "Feature",
                "id": r["id"],
                "geometry": r["geometry"],
                "properties": props
            })

        return {"type": "FeatureCollection", "features": features}

    async def _search_by_text(self, query: str) -> dict[str, Any]:
        """Búsqueda por texto usando FTS (search_vector) + ILIKE fallback sobre display_name.
        
        Ya no busca en properties->>'name' ni properties->>'nombre' directamente.
        Todo pasa por display_name y search_vector que fueron poblados por el normalizador.
        """
        # Features GIS
        # Usamos un Search Rank: FTS tiene peso 2, Similitud Trigámica tiene peso 5
        stmt_features = text("""
            SELECT 
                lf.id::text,
                lf.display_name,
                lf.layer_id::text,
                lf.properties,
                ST_AsGeoJSON(lf.geom)::json AS geometry,
                ARRAY[
                    ST_XMin(ST_Envelope(lf.geom)),
                    ST_YMin(ST_Envelope(lf.geom)),
                    ST_XMax(ST_Envelope(lf.geom)),
                    ST_YMax(ST_Envelope(lf.geom))
                ] AS bbox,
                (
                    ts_rank(lf.search_vector, plainto_tsquery('spanish', :q)) * 2 +
                    similarity(lf.display_name, :q) * 5
                ) AS search_rank
            FROM layer_features lf
            JOIN layers l ON l.id = lf.layer_id
            WHERE
                (lf.search_vector @@ plainto_tsquery('spanish', :q)
                OR unaccent(lf.display_name) ILIKE unaccent(:ilike)
                OR similarity(lf.display_name, :q) > 0.25)
                AND (NOT :public_only OR l.visibility = 'PUBLIC')
            ORDER BY search_rank DESC, lf.display_name
            LIMIT 15
        """)

        result_features = await self.db.execute(stmt_features, {
            "q": query,
            "ilike": f"%{query}%",
            "public_only": self.public_only,
        })
        features_rows = result_features.mappings().all()

        gis_features = []
        for r in features_rows:
            props = dict(r["properties"]) if r["properties"] else {}
            props["display_name"] = r["display_name"]
            props["layer_id"] = r["layer_id"]
            props["source"] = "feature"
            props["bbox"] = r["bbox"]
            gis_features.append({
                "type": "Feature",
                "id": r["id"],
                "geometry": r["geometry"],
                "properties": props
            })

        return {"type": "FeatureCollection", "features": gis_features}

    async def log_view(self, feature_id: int, source: str) -> None:
        """Actualiza la fecha de visualización de una entidad geográfica."""
        if source == "feature":
            stmt = text("""
                UPDATE layer_features AS lf
                SET last_viewed_at = NOW()
                WHERE lf.id = :id
                  AND (NOT :public_only OR EXISTS (
                      SELECT 1 FROM layers l
                      WHERE l.id = lf.layer_id AND l.visibility = 'PUBLIC'
                  ))
            """)
        else:
            return

        await self.db.execute(stmt, {"id": feature_id, "public_only": self.public_only})
        await self.db.commit()
