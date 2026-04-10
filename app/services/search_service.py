"""Servicio de búsqueda global del Geoportal.
Permite localizar geometrías (Features) y Proyectos mediante queries espaciales y de texto.

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

    def __init__(self, db: AsyncSession):
        self.db = db

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
            return await self._search_by_coordinates(lat, lon)

        return await self._search_by_text(query)

    async def get_suggestions(self, limit: int = 5) -> list[str]:
        """Obtiene sugerencias automáticas usando display_name."""
        # Features con display_name
        feature_stmt = text("""
            SELECT DISTINCT display_name FROM layer_features
            WHERE display_name IS NOT NULL
            ORDER BY RANDOM()
            LIMIT :limit
        """)
        features = (await self.db.execute(feature_stmt, {"limit": limit})).scalars().all()

        # Proyectos por nombre
        project_stmt = text("SELECT name FROM projects LIMIT :limit")
        projects = (await self.db.execute(project_stmt, {"limit": limit})).scalars().all()

        results = list(set([str(p) for p in list(features) + list(projects) if p]))
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
            WHERE ST_DWithin(
                lf.geom::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                2000
            )
            ORDER BY dist_metros ASC
            LIMIT 15
        """)

        result = await self.db.execute(stmt, {"lat": lat, "lon": lon})
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
        # 1. Features GIS
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
            WHERE
                lf.search_vector @@ plainto_tsquery('spanish', :q)
                OR unaccent(lf.display_name) ILIKE unaccent(:ilike)
                OR similarity(lf.display_name, :q) > 0.25
            ORDER BY search_rank DESC, lf.display_name
            LIMIT 15
        """)

        result_features = await self.db.execute(stmt_features, {
            "q": query,
            "ilike": f"%{query}%"
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

        # 2. Proyectos (Inmobiliarios)
        stmt_projects = text("""
            SELECT 
                p.id::text,
                p.name AS display_name,
                p.description,
                ST_AsGeoJSON(pl.geometry)::json AS geometry,
                ARRAY[
                    ST_XMin(ST_Envelope(pl.geometry)),
                    ST_YMin(ST_Envelope(pl.geometry)),
                    ST_XMax(ST_Envelope(pl.geometry)),
                    ST_YMax(ST_Envelope(pl.geometry))
                ] AS bbox,
                similarity(p.name, :q) as project_rank
            FROM projects p
            LEFT JOIN project_locations pl ON p.id = pl.project_id
            WHERE 
                to_tsvector('spanish', p.name) @@ plainto_tsquery('spanish', :q)
                OR unaccent(p.name) ILIKE unaccent(:ilike)
                OR similarity(p.name, :q) > 0.25
            ORDER BY project_rank DESC, p.name
            LIMIT 5
        """)
        result_projects = await self.db.execute(stmt_projects, {
            "q": query,
            "ilike": f"%{query}%"
        })
        project_rows = result_projects.mappings().all()

        project_features = []
        for p in project_rows:
            project_features.append({
                "type": "Feature",
                "id": str(p["id"]),
                "geometry": p["geometry"],
                "properties": {
                    "id": str(p["id"]),
                    "name": p["display_name"],
                    "display_name": p["display_name"],
                    "description": p["description"],
                    "source": "project",
                    "bbox": p["bbox"]
                }
            })

        return {
            "type": "FeatureCollection",
            "features": gis_features + project_features
        }

    async def log_view(self, feature_id: str, source: str) -> None:
        """Actualiza la fecha de visualización de una entidad o proyecto."""
        if source == "feature":
            stmt = text("""
                UPDATE layer_features 
                SET fecha_ubicado = NOW() 
                WHERE id = :id::uuid
            """)
        elif source == "project":
            stmt = text("""
                UPDATE projects 
                SET updated_at = NOW() 
                WHERE id = :id::uuid
            """)
        else:
            return

        await self.db.execute(stmt, {"id": feature_id})
        await self.db.commit()
