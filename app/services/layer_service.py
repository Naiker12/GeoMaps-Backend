"""Servicio de gestión de capas cartográficas vectoriales.
Orquestador de carga, transformación y persistencia de GeoJSON en PostGIS.
"""

import json
import logging
import uuid
from typing import Any, Sequence
from app.repositories.layer_repository import LayerRepository
from app.services.geo_service import GeoService
from app.schemas.layer import LayerCreate, LayerUpdate
from app.db.models.layer import Layer

logger = logging.getLogger(__name__)

VALID_GEOMETRY_TYPES = {"POINT", "LINESTRING", "POLYGON", "GEOMETRY"}
VALID_VISIBILITY = {"PUBLIC", "PRIVATE", "ADMIN_ONLY"}


class LayerService:
    """Implementa lógica de negocio para capas GIS (Vector Layers)."""

    def __init__(self, db: Any):
        self.repository = LayerRepository(db)
        self.geo_service = GeoService()

    async def get_layers(self, visibility: str | None = None) -> Sequence[Layer]:
        """Obtiene una lista de capas, opcionalmente filtrada por visibilidad."""
        return await self.list_layers(visibility=visibility)

    async def list_layers(self, visibility: str | None = None) -> Sequence[Layer]:
        """Obtiene una lista de capas, opcionalmente filtrada por visibilidad."""
        from app.db.models.layer import VisibilityEnum
        filters = {}
        if visibility:
            try:
                # Convertir string a Enum para evitar errores en el Repo/SQLAlchemy
                filters["visibility"] = VisibilityEnum(visibility.upper())
            except (ValueError, AttributeError):
                filters["visibility"] = visibility
                
        return await self.repository.get_multi(**filters)

    async def process_and_upload_layer(self, layer_in: LayerCreate, file: Any = None, user_id: uuid.UUID = None) -> Layer:
        """Alias para create_layer para compatibilidad con el router."""
        return await self.create_layer(layer_in, user_id, file)

    async def create_layer(self, layer_in: LayerCreate, user_id: uuid.UUID, file: Any = None) -> Layer:
        """Procesa y persiste una nueva capa con su geometría indexada."""
        if not file:
            raise ValueError("Se requiere un archivo GeoJSON/Shapefile")

        content = await file.read()
        geojson_data = json.loads(content)

        geom_type = await self.geo_service.get_geometry_type(geojson_data)
        processed_features = await self.geo_service.process_geojson(geojson_data)

        from app.services.storage_service import storage_service
        # Reset file cursor for upload after reading
        file.file.seek(0)
        file_url = await storage_service.upload_file(file, "layers")

        layer = await self.repository.create_layer(
            layer_in=layer_in,
            geometry_type=geom_type,
            source_type="FILE",
            file_url=file_url,
            user_id=user_id
        )

        await self.repository.insert_features_bulk(layer.id, processed_features)
        return layer

    async def update_layer(self, layer_id: uuid.UUID, layer_in: LayerUpdate | dict, file: Any = None) -> Layer | None:
        """Actualiza metadatos o reemplaza la geometría de una capa existente."""
        layer = await self.repository.get(layer_id)
        if not layer:
            return None

        if isinstance(layer_in, dict):
            update_data = layer_in
        else:
            update_data = layer_in.model_dump(exclude_unset=True)
        
        if file:
            from app.services.storage_service import storage_service
            update_data["file_url"] = await storage_service.upload_file(file, "layers")
            
        return await self.repository.update(layer, update_data)

    async def get_layer_geojson(self, layer_id: uuid.UUID) -> dict:
        """Retorna la colección completa de features en formato GeoJSON."""
        return await self.repository.get_features_as_geojson(layer_id)

    async def get_features_properties(self, layer_ids: list[uuid.UUID]) -> list[dict]:
        """Extrae propiedades alfanuméricas de múltiples capas para analíticas."""
        return await self.repository.get_features_properties(layer_ids)

    async def get_feature_by_id(self, feature_id: Any) -> dict | None:
        """Obtiene el detalle de una sola entidad geográfica."""
        return await self.repository.get_feature_by_id(feature_id)

    async def delete_layer(self, layer_id: uuid.UUID) -> bool:
        """Elimina físicamente una capa y todas sus entidades geográficas."""
        return await self.repository.delete(layer_id)
