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


class SearchService:
    """Implementa búsquedas transversales (Geográficas y Alfanuméricas)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(self, query: str) -> dict[str, Any]:
        """Realiza una búsqueda global mediante el motor integrado."""
        query = query.strip()
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
        stmt_features = text("""
            SELECT 
                lf.id::text,
                lf.display_name,
                lf.layer_id::text,
                lf.properties,
                ST_AsGeoJSON(lf.geom)::json AS geometry,
                ts_rank(
                    lf.search_vector,
                    plainto_tsquery('spanish', :q)
                ) AS rank
            FROM layer_features lf
            WHERE
                lf.search_vector @@ plainto_tsquery('spanish', :q)
                OR lf.display_name ILIKE :ilike
            ORDER BY rank DESC, lf.display_name
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
            gis_features.append({
                "type": "Feature",
                "id": r["id"],
                "geometry": r["geometry"],
                "properties": props
            })

        # 2. Proyectos
        stmt_projects = text("""
            SELECT id::text, name, description
            FROM projects
            WHERE name ILIKE :ilike
            LIMIT 5
        """)
        result_projects = await self.db.execute(stmt_projects, {"ilike": f"%{query}%"})
        project_rows = result_projects.mappings().all()

        project_features = [
            {
                "type": "Feature",
                "id": str(p["id"]),
                "geometry": None,
                "properties": {
                    "name": p["name"],
                    "display_name": p["name"],
                    "description": p["description"],
                    "source": "project"
                }
            }
            for p in project_rows
        ]

        return {
            "type": "FeatureCollection",
            "features": project_features + gis_features
        }
