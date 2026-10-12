import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.download import DownloadResource
from app.repositories.download_repository import DownloadRepository
from app.schemas.download import DownloadResourceCreate


class DownloadService:
    def __init__(self, db: AsyncSession):
        self.repository = DownloadRepository(db)

    async def create_download(
        self,
        download_in: DownloadResourceCreate,
        user_id: uuid.UUID,
        file_url: str | None = None,
    ) -> DownloadResource:
        return await self.repository.create_download(download_in, file_url, user_id)

    async def get_downloads(
        self,
        show_in_public: bool | None = None,
        skip: int = 0,
        limit: int = 100,
        *, is_published: bool | None = None,
    ) -> Sequence[DownloadResource]:
        return await self.repository.get_all(
            show_in_public=show_in_public,
            skip=skip,
            limit=limit,
            is_published=is_published,
        )

    async def update_resource_metadata(
        self,
        resource_id: uuid.UUID,
        metadata: dict,
    ) -> DownloadResource | None:
        resource = await self.repository.get(resource_id)
        if not resource:
            return None

        update_data = {key: value for key, value in metadata.items() if value is not None}
        return await self.repository.update(resource, update_data)

    async def delete_download(self, download_id: uuid.UUID) -> bool:
        return await self.repository.delete(download_id)
