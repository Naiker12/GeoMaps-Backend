"""Servicio para gestión de recursos descargables.
Maneja la lógica de negocio para PDF, ZIP y archivos geoespaciales.
"""

import logging
import httpx
from typing import Any, Sequence
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
        user_id: Any, 
        files: list = []
    ) -> DownloadResource:
        """Crea un nuevo recurso y opcionalmente procesa el archivo físico."""
        file_url = None
        if files and len(files) > 0:
            file = files[0] # Tomamos el primer archivo
            from app.services.storage_service import storage_service
            file_url = await storage_service.upload_file(file, "resources")
            
        return await self.repository.create_download(download_in, file_url, user_id)

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
            return {"error": "Inalcanzable"}
