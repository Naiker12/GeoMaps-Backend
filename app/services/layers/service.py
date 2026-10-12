"""Servicio de gestión de capas cartográficas vectoriales."""

import json
import logging
import uuid
import tempfile
from pathlib import Path
from typing import Any, Sequence

import geopandas as gpd
from starlette.concurrency import run_in_threadpool

from app.repositories.layer_repository import LayerRepository
from app.services.geospatial import GeoService
from app.schemas.layer import LayerCreate, LayerUpdate
from app.db.models.layer import Layer
from app.db.models.user import User
from app.core.security.ownership import ensure_resource_owner
from app.services.storage import MAX_FILE_SIZE, FileTooLargeError

logger = logging.getLogger(__name__)


class LayerService:
    def __init__(self, db: Any):
        self.db = db
        self.repository = LayerRepository(db)
        self.geo_service = GeoService()

    async def list_layers(
        self,
        visibility: str | None = None,
        category: str | None = None,
        subcategory: str | None = None,
    ) -> Sequence[Layer]:
        from app.db.models.layer import VisibilityEnum

        filters = {}
        if visibility:
            try:
                filters["visibility"] = VisibilityEnum(visibility.upper())
            except Exception:
                filters["visibility"] = visibility
        if category:
            filters["category"] = self._clean_text(category)
        if subcategory:
            filters["subcategory"] = self._clean_text(subcategory)

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

        uploaded_url = None
        committed = False
        try:
            layer_in = self._normalize_layer_input(layer_in)
            geojson_data = await self._parse_file(file)

            geom_type = await self.geo_service.get_geometry_type(geojson_data)
            processed_features = await self.geo_service.process_geojson(geojson_data)

            from app.services.storage import storage_service

            await file.seek(0)

            file_url = await storage_service.upload_file(file, "layers")
            uploaded_url = file_url

            layer = await self.repository.create_layer(
                layer_in=layer_in,
                geometry_type=geom_type,
                source_type="FILE",
                file_url=file_url,
                user_id=user_id,
                commit=False,
            )

            await self.repository.insert_features_bulk(layer.id, processed_features, commit=False)
            await self.db.commit()
            committed = True
            await self.db.refresh(layer)

            return layer

        except Exception as e:
            await self.db.rollback()
            if uploaded_url and not committed:
                await self._remove_file_best_effort(uploaded_url)
            if isinstance(e, ValueError):
                raise
            logger.exception("Error inesperado creando capa")
            raise RuntimeError("No se pudo guardar la capa") from e

    async def _parse_file(self, file: Any) -> dict:
        filename = (file.filename or "").lower()
        try:
            content = await file.read(MAX_FILE_SIZE + 1)
            if len(content) > MAX_FILE_SIZE:
                raise FileTooLargeError("Archivo demasiado grande")
            return await run_in_threadpool(self._parse_content, filename, content)
        finally:
            await file.seek(0)

    @staticmethod
    def _parse_content(filename: str, content: bytes) -> dict:
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

            try:
                gdf = gpd.read_file(f"zip://{tmp_path}")
                if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
                    gdf = gdf.to_crs(epsg=4326)
                return json.loads(gdf.to_json())
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        else:
            raise ValueError("Formato no soportado. Usa .geojson o .zip")

    async def update_layer(
        self,
        layer_id: uuid.UUID,
        layer_in: LayerUpdate | dict,
        file: Any = None,
        *, actor: User,
    ) -> Layer | None:
        layer = await self.repository.get(layer_id, for_update=True)
        if not layer:
            return None
        try:
            ensure_resource_owner(actor, layer.created_by)
        except PermissionError:
            await self.db.rollback()
            raise

        if isinstance(layer_in, dict):
            update_data = layer_in
        else:
            update_data = layer_in.model_dump(exclude_unset=True)

        update_data = self._normalize_update_data(update_data)

        old_url = layer.file_url if file else None
        uploaded_url = None
        committed = False
        try:
            if file:
                from app.services.storage import storage_service

                geojson_data = await self._parse_file(file)
                geom_type = await self.geo_service.get_geometry_type(geojson_data)
                processed_features = await self.geo_service.process_geojson(geojson_data)
                await file.seek(0)
                uploaded_url = await storage_service.upload_file(file, "layers")
                update_data["file_url"] = uploaded_url
                update_data["geometry_type"] = geom_type
                await self.repository.delete_features_by_layer_id(layer_id, commit=False)
                await self.repository.insert_features_bulk(layer_id, processed_features, commit=False)

            layer = await self.repository.update(layer, update_data, commit=False)
            await self.db.commit()
            committed = True
            await self.db.refresh(layer)
        except Exception:
            await self.db.rollback()
            if uploaded_url and not committed:
                await self._remove_file_best_effort(uploaded_url)
            raise
        if old_url and uploaded_url and old_url != uploaded_url:
            await self._remove_file_best_effort(old_url)
        return layer

    async def _remove_file_best_effort(self, file_url: str) -> None:
        from app.services.storage import storage_service

        try:
            if not await storage_service.delete_file(file_url):
                logger.warning("No se pudo retirar un archivo de storage; requiere limpieza posterior")
        except Exception:
            logger.exception("Falló la limpieza del archivo de storage")

    async def get_layer_geojson(self, layer_id: uuid.UUID, *, public_only: bool = False) -> dict:
        return await self.repository.get_features_as_geojson(layer_id, public_only=public_only)

    async def get_features_properties(self, layer_ids: list[uuid.UUID], *, public_only: bool = False) -> list[dict]:
        return await self.repository.get_features_properties(layer_ids, public_only=public_only)

    async def get_feature_by_id(self, feature_id: Any, *, public_only: bool = False) -> dict | None:
        return await self.repository.get_feature_by_id(feature_id, public_only=public_only)

    async def delete_layer(self, layer_id: uuid.UUID, *, actor: User) -> bool:
        layer = await self.repository.get(layer_id, for_update=True)
        if not layer:
            return False
        try:
            ensure_resource_owner(actor, layer.created_by)
        except PermissionError:
            await self.db.rollback()
            raise

        file_url = layer.file_url
        deleted = await self.repository.delete(layer_id)
        if deleted and file_url:
            await self._remove_file_best_effort(file_url)
        return deleted

    async def get_field_values(self, layer_id: uuid.UUID, field: str, *, public_only: bool = False) -> dict:
        """Valores únicos de un campo para simbología categorizada."""
        return await self.repository.get_field_values(layer_id, field, public_only=public_only)

    async def get_field_stats(self, layer_id: uuid.UUID, field: str, *, public_only: bool = False) -> dict:
        """Estadísticas numéricas de un campo para simbología graduada."""
        return await self.repository.get_field_stats(layer_id, field, public_only=public_only)

    async def get_categories(self, *, public_only: bool = False) -> list[str]:
        """Obtiene el listado de categorías únicas."""
        return await self.repository.get_unique_categories(public_only=public_only)

    async def get_categories_tree(self, *, public_only: bool = False) -> list[dict]:
        """Obtiene categorias con subcategorias y conteo de capas."""
        return await self.repository.get_categories_tree(public_only=public_only)

    def _clean_text(self, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def _normalize_layer_input(self, layer_in: LayerCreate) -> LayerCreate:
        data = layer_in.model_dump()
        normalized = self._normalize_update_data(data)
        return LayerCreate(**normalized)

    def _normalize_update_data(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(data)
        for field in ("name", "description", "category", "subcategory", "source", "visibility"):
            if field in normalized:
                normalized[field] = self._clean_text(normalized[field])
        return normalized
