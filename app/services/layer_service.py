"""Servicio de gestión de capas cartográficas vectoriales."""

import json
import logging
import uuid
import tempfile
from typing import Any, Sequence

import geopandas as gpd

from app.repositories.layer_repository import LayerRepository
from app.services.geo_service import GeoService
from app.schemas.layer import LayerCreate, LayerUpdate
from app.db.models.layer import Layer

logger = logging.getLogger(__name__)


class LayerService:
    def __init__(self, db: Any):
        self.repository = LayerRepository(db)
        self.geo_service = GeoService()

    async def list_layers(self, visibility: str | None = None) -> Sequence[Layer]:
        from app.db.models.layer import VisibilityEnum

        filters = {}
        if visibility:
            try:
                filters["visibility"] = VisibilityEnum(visibility.upper())
            except Exception:
                filters["visibility"] = visibility

        return await self.repository.get_multi(**filters)

    async def process_and_upload_layer(
        self, layer_in: LayerCreate, file: Any = None, user_id: uuid.UUID = None
    ) -> Layer:
        return await self.create_layer(layer_in, user_id, file)

    async def create_layer(
        self, layer_in: LayerCreate, user_id: uuid.UUID, file: Any = None
    ) -> Layer:
        if not file:
            raise ValueError("Se requiere un archivo (.geojson o .zip)")

        try:
            geojson_data = await self._parse_file(file)

            geom_type = await self.geo_service.get_geometry_type(geojson_data)
            processed_features = await self.geo_service.process_geojson(geojson_data)

            from app.services.storage_service import storage_service

            file.file.seek(0)

            file_url = await storage_service.upload_file(file, "layers")

            layer = await self.repository.create_layer(
                layer_in=layer_in,
                geometry_type=geom_type,
                source_type="FILE",
                file_url=file_url,
                user_id=user_id,
            )

            await self.repository.insert_features_bulk(layer.id, processed_features)

            return layer

        except ValueError:
            raise
        except Exception as e:
            logger.exception("Error inesperado creando capa")
            raise ValueError(f"Fallo procesando capa: {str(e)}")

    async def _parse_file(self, file: Any) -> dict:
        filename = file.filename.lower()
        content = await file.read()

        if filename.endswith(".geojson") or filename.endswith(".json"):
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("latin-1")

            return json.loads(text)

        elif filename.endswith(".zip"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            gdf = gpd.read_file(f"zip://{tmp_path}")

            if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
                gdf = gdf.to_crs(epsg=4326)

            return json.loads(gdf.to_json())

        else:
            raise ValueError("Formato no soportado. Usa .geojson o .zip")

    async def update_layer(
        self,
        layer_id: uuid.UUID,
        layer_in: LayerUpdate | dict,
        file: Any = None,
    ) -> Layer | None:
        layer = await self.repository.get(layer_id)
        if not layer:
            return None

        if isinstance(layer_in, dict):
            update_data = layer_in
        else:
            update_data = layer_in.model_dump(exclude_unset=True)

        if file:
            from app.services.storage_service import storage_service

            # 1. Parsear el nuevo archivo
            geojson_data = await self._parse_file(file)

            # 2. Obtener metadatos y features procesados
            geom_type = await self.geo_service.get_geometry_type(geojson_data)
            processed_features = await self.geo_service.process_geojson(geojson_data)

            # 3. Limpiar features antiguos
            await self.repository.delete_features_by_layer_id(layer_id)

            # 4. Insertar nuevos features
            await self.repository.insert_features_bulk(layer_id, processed_features)

            # 5. Subir archivo al storage
            file.file.seek(0)
            update_data["file_url"] = await storage_service.upload_file(file, "layers")
            update_data["geometry_type"] = geom_type

        return await self.repository.update(layer, update_data)

    async def get_layer_geojson(self, layer_id: uuid.UUID) -> dict:
        return await self.repository.get_features_as_geojson(layer_id)

    async def get_features_properties(self, layer_ids: list[uuid.UUID]) -> list[dict]:
        return await self.repository.get_features_properties(layer_ids)

    async def get_feature_by_id(self, feature_id: Any) -> dict | None:
        return await self.repository.get_feature_by_id(feature_id)

    async def delete_layer(self, layer_id: uuid.UUID) -> bool:
        layer = await self.repository.get(layer_id)
        if not layer:
            return False

        from app.services.storage_service import storage_service

        if layer.file_url:
            deleted = await storage_service.delete_file(layer.file_url)
            if not deleted:
                logger.warning(
                    f"No se pudo eliminar el archivo del storage para capa {layer_id}. "
                    f"URL: {layer.file_url} — Se elimina la capa de todas formas."
                )

        return await self.repository.delete(layer_id)

    async def get_field_values(self, layer_id: uuid.UUID, field: str) -> dict:
        """Valores únicos de un campo para simbología categorizada."""
        return await self.repository.get_field_values(layer_id, field)

    async def get_field_stats(self, layer_id: uuid.UUID, field: str) -> dict:
        """Estadísticas numéricas de un campo para simbología graduada."""
        return await self.repository.get_field_stats(layer_id, field)