"""Servicio para gestión de recursos descargables.
Maneja la lógica de negocio para PDF, ZIP y archivos geoespaciales.
"""

import logging
import httpx
from typing import Any, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.download import DownloadResource
from app.repositories.download_repository import DownloadRepository
from app.schemas.download import DownloadResourceCreate

logger = logging.getLogger(__name__)


class DownloadService:
    """Orquestador de recursos para visores cartográficos."""

    def __init__(self, db: AsyncSession):
        self.repository = DownloadRepository(db)

    async def get_downloads(self, show_in_public: bool | None = None) -> Sequence[DownloadResource]:
        """Obtiene recursos filtrando por visibilidad."""
        return await self.repository.get_all(show_in_public=show_in_public)

    async def create_download(
        self, 
        download_in: DownloadResourceCreate, 
        user_id: Any
    ) -> DownloadResource:
        """Crea un nuevo recurso de descarga (con soporte para sincronización de capas)."""
        data = download_in.model_dump()
        data["created_by"] = user_id
        
        # Si viene vinculada a una capa, precargar metadatos desde el modelo Layer
        if data.get("layer_id"):
            from app.db.models.layer import Layer
            stmt = select(Layer).where(Layer.id == data["layer_id"])
            result = await self.repository.db.execute(stmt)
            layer = result.scalar_one_or_none()
            
            if layer:
                data["file_url"] = layer.file_url
                data["file_format"] = layer.source_type
                data["geometry_type"] = layer.geometry_type
                # El content_count se podría sacar de count(layer.features)
                from app.db.models.layer import LayerFeature
                from sqlalchemy import func
                count_stmt = select(func.count()).where(LayerFeature.layer_id == layer.id)
                count_res = await self.repository.db.execute(count_stmt)
                data["content_count"] = count_res.scalar()

        return await self.repository.create(data)

    async def update_resource_metadata(self, resource_id: Any, metadata: dict) -> DownloadResource | None:
        """Actualiza metadatos técnicos tras la subida del archivo."""
        db_obj = await self.repository.get(resource_id)
        if not db_obj:
            return None
        
        return await self.repository.update(db_obj, metadata)

    async def delete_download(self, download_id: Any) -> bool:
        """Invalida un recurso por su identificador único."""
        return await self.repository.delete(download_id)

    async def fetch_external_metadata(self, url: str) -> dict[str, Any]:
        """Obtiene metadatos de recursos remotos con cliente HTTP asíncrono."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            logger.error(f"Error externo: {exc}")
            return {"error": str(exc)}
