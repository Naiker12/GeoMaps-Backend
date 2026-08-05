"""Repositorio de recursos de descarga.
Extiende BaseRepository para heredar operaciones CRUD genéricas.
"""

import uuid
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.download import DownloadResource
from app.repositories.base_repository import BaseRepository
from app.schemas.download import DownloadResourceCreate


class DownloadRepository(BaseRepository[DownloadResource]):
    """Gestión de recursos para el visor cartográfico."""

    def __init__(self, db: AsyncSession):
        super().__init__(DownloadResource, db)

    async def get_all(
        self, 
        show_in_public: bool | None = None,
        skip: int = 0,
        limit: int = 100
    ) -> Sequence[DownloadResource]:
        """Obtiene recursos filtrando por visibilidad y orden cronológico."""
        stmt = (
            select(self.model)
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        
        if show_in_public is not None:
            stmt = stmt.where(self.model.show_in_public == show_in_public)
            
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create_download(
        self, 
        download_in: DownloadResourceCreate, 
        file_url: str | None, 
        user_id: uuid.UUID
    ) -> DownloadResource:
        """Helper especializado para creación con metadatos y archivos."""
        data = download_in.model_dump()
        # Mapeo de campos schema -> modelo
        data["file_url"] = file_url
        data["created_by"] = user_id
        
        return await self.create(data)
