"""Repositorio de capas vectoriales (PostGIS).
Extiende BaseRepository para heredar operaciones CRUD genéricas.
"""

import json
import uuid
from typing import Any, Sequence

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.layer import Layer, LayerFeature
from app.repositories.base_repository import BaseRepository
from app.schemas.layer import LayerCreate


class LayerRepository(BaseRepository[Layer]):
    """Gestor de capas y features geoespaciales."""

    def __init__(self, db: AsyncSession):
        super().__init__(Layer, db)

    async def create_layer(
        self, 
        layer_in: LayerCreate, 
        geometry_type: str, 
        source_type: str, 
        file_url: str, 
        user_id: uuid.UUID
    ) -> Layer:
        """Helper especializado para creación con metadatos cartográficos."""
        data = layer_in.model_dump()
        data.update({
            "geometry_type": geometry_type,
            "source_type": source_type,
            "file_url": file_url,
            "created_by": user_id,
            "visibility": layer_in.visibility.upper()
        })
        return await self.create(data)

    async def get_unique_categories(self) -> list[str]:
        """Obtiene el listado de categorías únicas registradas."""
        stmt = select(Layer.category).distinct().where(Layer.category.is_not(None)).order_by(Layer.category)
        result = await self.db.execute(stmt)
        return [c for c in result.scalars().all() if c]

    async def get_categories_tree(self) -> list[dict]:
        """Agrupa categorias y subcategorias a partir de las capas existentes."""
        stmt = (
            select(Layer.category, Layer.subcategory, func.count(Layer.id).label("layers_count"))
            .where(Layer.category.is_not(None))
            .group_by(Layer.category, Layer.subcategory)
            .order_by(Layer.category, Layer.subcategory)
        )
        result = await self.db.execute(stmt)

        grouped: dict[str, dict] = {}
        for category, subcategory, layers_count in result.all():
            if not category:
                continue

            item = grouped.setdefault(
                category,
                {"category": category, "subcategories": set(), "layers_count": 0},
            )
            if subcategory:
                item["subcategories"].add(subcategory)
            item["layers_count"] += int(layers_count or 0)

        return [
            {
                "category": item["category"],
                "subcategories": sorted(item["subcategories"]),
                "layers_count": item["layers_count"],
            }
            for item in grouped.values()
        ]

    async def insert_features_bulk(self, layer_id: uuid.UUID, features: list[dict]):
        """Inserta features cartográficas en lotes para mayor rendimiento."""
        if not features: return
            
        mappings = [
            {
                "layer_id": layer_id,
                "display_name": feat.get("display_name"),
                "properties": feat["properties"],
                # PostGIS: Convertir WKT a GEOMETRY indexable
                "geom": text(f"ST_GeomFromText('{feat['geom_wkt']}', 4326)")
            }
            for feat in features
        ]
            
        chunk_size = 500
        for i in range(0, len(mappings), chunk_size):
            await self.db.execute(insert(LayerFeature).values(mappings[i:i + chunk_size]))
        
        await self.db.commit()
    
    async def delete_features_by_layer_id(self, layer_id: uuid.UUID) -> bool:
        """Elimina todos los elementos geográficos asociados a una capa."""
        stmt = delete(LayerFeature).where(LayerFeature.layer_id == layer_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0

    async def get_features_as_geojson(self, layer_id: uuid.UUID) -> dict:
        """Representa las geometrías de la capa como un FeatureCollection GeoJSON."""
        stmt = select(
            LayerFeature.id, 
            LayerFeature.properties, 
            func.ST_AsGeoJSON(LayerFeature.geom).label('geometry')
        ).where(LayerFeature.layer_id == layer_id)
        
        result = await self.db.execute(stmt)
        rows = result.mappings().all()
        
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": str(row['id']),
                    "properties": row['properties'],
                    "geometry": json.loads(row['geometry'])
                }
                for row in rows
            ]
        }

    async def get_features_properties(self, layer_ids: list[uuid.UUID]) -> list[dict]:
        """Obtiene de forma eficiente las propiedades para paneles estadísticos."""
        stmt = select(LayerFeature.properties).where(LayerFeature.layer_id.in_(layer_ids))
        result = await self.db.execute(stmt)
        return [{"properties": p} for p in result.scalars().all()]

    async def get_feature_by_id(self, feature_id: Any) -> dict | None:
        """Detalle de una sola entidad geográfica. Soporta IDs numéricos."""
        try:
            # Intentar convertir a entero si es posible, ya que la columna es BigInt
            if isinstance(feature_id, str) and feature_id.isdigit():
                f_id = int(feature_id)
            elif isinstance(feature_id, (int, float)):
                f_id = int(feature_id)
            else:
                # Si no es un número, intentar UUID por si acaso aunque la base diga BigInt
                f_id = uuid.UUID(str(feature_id))
        except (ValueError, TypeError):
            return None

        stmt = select(
            LayerFeature.id,
            LayerFeature.layer_id,
            LayerFeature.properties,
            LayerFeature.created_at,
            func.ST_AsGeoJSON(LayerFeature.geom).label('geometry')
        ).where(LayerFeature.id == f_id)

        try:
            result = await self.db.execute(stmt)
            row = result.mappings().first()
            
            if not row:
                return None
                
            return {
                "id": str(row['id']),
                "layer_id": str(row['layer_id']),
                "properties": row['properties'],
                "lastUpdate": row['created_at'].isoformat() if row['created_at'] else None,
                "geometry": json.loads(row['geometry'])
            }
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error en get_feature_by_id: {e}")
            return None

    async def get_field_values(self, layer_id: uuid.UUID, field_name: str) -> dict:
        """Obtiene valores únicos de un campo JSONB para simbología categorizada."""
        stmt = text(
            "SELECT DISTINCT properties->>:field AS val "
            "FROM layer_features WHERE layer_id = :lid AND properties->>:field IS NOT NULL "
            "ORDER BY val LIMIT 100"
        )
        result = await self.db.execute(stmt, {"field": field_name, "lid": str(layer_id)})
        values = [row[0] for row in result.fetchall()]
        return {"field": field_name, "values": values, "total_unique": len(values)}

    async def get_field_stats(self, layer_id: uuid.UUID, field_name: str) -> dict:
        """Obtiene estadísticas numéricas de un campo JSONB para simbología graduada."""
        stmt = text(
            "SELECT "
            "  MIN((properties->>:field)::numeric) AS min_val, "
            "  MAX((properties->>:field)::numeric) AS max_val, "
            "  AVG((properties->>:field)::numeric) AS avg_val, "
            "  COUNT(*) AS cnt "
            "FROM layer_features "
            "WHERE layer_id = :lid "
            "  AND properties->>:field IS NOT NULL "
            "  AND (properties->>:field) ~ '^-?[0-9]+(\\.[0-9]+)?$'"
        )
        result = await self.db.execute(stmt, {"field": field_name, "lid": str(layer_id)})
        row = result.fetchone()
        if not row or row[3] == 0:
            return {"field": field_name, "min": None, "max": None, "avg": None, "count": 0}
        return {
            "field": field_name,
            "min": float(row[0]),
            "max": float(row[1]),
            "avg": round(float(row[2]), 2),
            "count": int(row[3])
        }
