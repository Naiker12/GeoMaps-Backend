import uuid
import json
from typing import List, Optional
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
        query = """
        SELECT id, properties, ST_AsGeoJSON(geom) as geometry
        FROM layer_features
        WHERE layer_id = :layer_id
        """
        
        result = await self.db.execute(text(query), {"layer_id": str(layer_id)})
        
        features = []
        for row in result:
            features.append({
                "type": "Feature",
                "id": row._mapping['id'],
                "properties": row._mapping['properties'],
                "geometry": json.loads(row._mapping['geometry'])
            })
            
        return {
            "type": "FeatureCollection",
            "features": features
        }

    async def delete_layer(self, layer_id: uuid.UUID) -> bool:
        db_layer = await self.get_by_id(layer_id)
        if not db_layer:
            return False
            
        await self.db.delete(db_layer)
        await self.db.commit()
        return True
