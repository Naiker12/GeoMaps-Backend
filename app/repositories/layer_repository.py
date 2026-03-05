import uuid
import json
from typing import Any, List, Optional
from sqlalchemy import text, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.layer import Layer, LayerFeature
from app.schemas.layer import LayerCreate

class LayerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self, visibility: Optional[str] = None) -> List[Layer]:
        stmt = select(Layer)
        if visibility:
            stmt = stmt.where(Layer.visibility == visibility)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, layer_id: uuid.UUID) -> Optional[Layer]:
        stmt = select(Layer).where(Layer.id == layer_id)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def create_layer(self, layer_in: LayerCreate, geometry_type: str, source_type: str, file_url: str, user_id: uuid.UUID) -> Layer:
        db_layer = Layer(
            name=layer_in.name,
            description=layer_in.description,
            category=layer_in.category,
            source=layer_in.source,
            visibility=layer_in.visibility,
            geometry_type=geometry_type,
            source_type=source_type,
            file_url=file_url,
            created_by=user_id
        )
        self.db.add(db_layer)
        await self.db.commit()
        await self.db.refresh(db_layer)
        return db_layer

    async def insert_features_bulk(self, layer_id: uuid.UUID, features_data: List[dict]):
        """
        Inserta en bulk (lotes) características geométricas a `layer_features`.
        features_data es una lista de diccionarios:
        [{ "properties": dict, "geom_wkt": str }, ...]
        """
        if not features_data:
            return
            
        mappings = []
        for feat in features_data:
            mappings.append({
                "layer_id": layer_id,
                "properties": feat["properties"],
                # Usar ST_GeomFromText() para que PostGIS convierta de WKT a GEOMETRY
                "geom": text(f"ST_GeomFromText('{feat['geom_wkt']}', 4326)")
            })
            
        # Ejecutando un insert bulk (por chunks sería ideal para archivos enormes)
        chunk_size = 1000
        for i in range(0, len(mappings), chunk_size):
            chunk = mappings[i:i + chunk_size]
            await self.db.execute(insert(LayerFeature).values(chunk))
        
        await self.db.commit()

    async def get_features_as_geojson(self, layer_id: uuid.UUID) -> dict:
        """
        Retorna las geometrías de una capa como Point/Polygons mapeados en un GeoJSON (FeatureCollection).
        """
        # Usamos func.ST_AsGeoJSON para el procesamiento GIS
        from sqlalchemy import func
        stmt = select(
            LayerFeature.id, 
            LayerFeature.properties, 
            func.ST_AsGeoJSON(LayerFeature.geom).label('geometry')
        ).where(LayerFeature.layer_id == layer_id)
        
        result = await self.db.execute(stmt)
        rows = result.mappings().all()
        
        features = []
        for row in rows:
            features.append({
                "type": "Feature",
                "id": row['id'],
                "properties": row['properties'],
                "geometry": json.loads(row['geometry'])
            })
            
        return {
            "type": "FeatureCollection",
            "features": features
        }

    async def get_features_properties(self, layer_ids: List[uuid.UUID]) -> List[dict]:
        """
        Retorna solo las propiedades de las features para las capas especificadas.
        Optimizado para estadísticas dinámicas.
        """
        stmt = select(LayerFeature.properties).where(LayerFeature.layer_id.in_(layer_ids))
        result = await self.db.execute(stmt)
        return [{"properties": p} for p in result.scalars().all()]

    async def get_feature_by_id(self, feature_id: Any) -> Optional[dict]:
        """
        Retorna una sola feature con sus propiedades y geometría.
        """
        from sqlalchemy import func
        # Intentar convertir feature_id a UUID si es necesario
        try:
            f_id = uuid.UUID(str(feature_id))
            stmt = select(
                LayerFeature.id,
                LayerFeature.layer_id,
                LayerFeature.properties,
                LayerFeature.created_at,
                func.ST_AsGeoJSON(LayerFeature.geom).label('geometry')
            ).where(LayerFeature.id == f_id)
        except (ValueError, TypeError):
            # Si no es UUID, intentar como entero si el ID en DB lo fuera
            try:
                f_id_int = int(str(feature_id))
                stmt = select(
                    LayerFeature.id,
                    LayerFeature.layer_id,
                    LayerFeature.properties,
                    LayerFeature.created_at,
                    func.ST_AsGeoJSON(LayerFeature.geom).label('geometry')
                ).where(LayerFeature.id == f_id_int)
            except ValueError:
                return None

        result = await self.db.execute(stmt)
        row = result.mappings().first()
        if not row:
            return None
            
        return {
            "id": row['id'],
            "layer_id": row['layer_id'],
            "properties": row['properties'],
            "lastUpdate": row['created_at'],
            "geometry": json.loads(row['geometry'])
        }

    async def delete_layer(self, layer_id: uuid.UUID) -> bool:
        db_layer = await self.get_by_id(layer_id)
        if not db_layer:
            return False
            
        await self.db.delete(db_layer)
        await self.db.commit()
        return True
