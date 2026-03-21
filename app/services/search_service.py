"""Servicio de búsqueda global del Geoportal.
Permite localizar geometrías (Features) y Proyectos mediante queries espaciales y de texto.
"""

import logging
import re
from typing import Any, Sequence
from sqlalchemy import select, text, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.layer import LayerFeature
from app.db.models.project import Project

logger = logging.getLogger(__name__)

COORD_REGEX = re.compile(r"^(-?\d+(\.\d+)?)\s*,?\s*(-?\d+(\.\d+)?)$")


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
            lon = float(coord_match.group(3))
            return await self._search_by_coordinates(lat, lon)

        return await self._search_by_text(query)

    async def get_suggestions(self, limit: int = 5) -> list[str]:
        """Obtiene sugerencias automáticas de proyectos y capas."""
        project_stmt = select(Project.name).limit(limit)
        
        # Buscamos en 'nombre' o 'name' dentro de properties
        feature_stmt = select(
            func.coalesce(
                LayerFeature.properties["nombre"].astext,
                LayerFeature.properties["name"].astext
            )
        ).where(
            or_(
                LayerFeature.properties["nombre"].astext != None,
                LayerFeature.properties["name"].astext != None
            )
        ).limit(limit)

        projects = (await self.db.execute(project_stmt)).scalars().all()
        features = (await self.db.execute(feature_stmt)).scalars().all()

        results = list(set([str(p) for p in (projects + features) if p]))
        return results[:limit]

    async def _search_by_coordinates(self, lat: float, lon: float) -> dict[str, Any]:
        """Localiza entidades geográficas por proximidad espacial (Radio de 1km)."""
        point_wkt = f"POINT({lon} {lat})"
        stmt = text("""
            SELECT id, properties, ST_AsGeoJSON(geom)::json as geometry, 'feature' as source
            FROM layer_features
            WHERE ST_DWithin(geom, ST_GeomFromText(:wkt, 4326), 1000)
            LIMIT 50
        """)
        
        result = await self.db.execute(stmt, {"wkt": point_wkt})
        rows = result.mappings().all()

        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": str(r["id"]),
                    "geometry": r["geometry"],
                    "properties": {**r["properties"], "source": r["source"]}
                }
                for r in rows
            ]
        }

    async def _search_by_text(self, query: str) -> dict[str, Any]:
        """Ejecuta búsquedas de texto plano enriquecidas con ILIKE."""
        # 1. Búsqueda en Proyectos
        stmt_projects = select(Project).where(Project.name.ilike(f"%{query}%")).limit(10)
        projects = (await self.db.execute(stmt_projects)).scalars().all()

        stmt_features = text("""
            SELECT id, layer_id, properties, ST_AsGeoJSON(geom)::json as geometry
            FROM layer_features
            WHERE properties->>'name' ILIKE :q OR properties->>'nombre' ILIKE :q
            LIMIT 10
        """)
        
        result_features = await self.db.execute(stmt_features, {"q": f"%{query}%"})
        features = result_features.mappings().all()

        project_features = [
            {
                "type": "Feature",
                "id": str(p.id),
                "geometry": None,
                "properties": {"name": p.name, "description": p.description, "source": "project"}
            }
            for p in projects
        ]

        gis_features = [
            {
                "type": "Feature",
                "id": str(f["id"]),
                "geometry": f["geometry"],
                "properties": {**f["properties"], "layer_id": str(f["layer_id"]), "source": "feature"}
            }
            for f in features
        ]

        return {
            "type": "FeatureCollection",
            "features": project_features + gis_features
        }
