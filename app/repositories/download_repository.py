import uuid
from typing import Any, List, Optional
from sqlalchemy import text, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.download import DownloadResource
from app.schemas.download import DownloadResourceCreate

class DownloadRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self, show_in_public: Optional[bool] = None) -> List[DownloadResource]:
        stmt = select(DownloadResource)
        if show_in_public is not None:
            stmt = stmt.where(DownloadResource.show_in_public == show_in_public)
        stmt = stmt.order_by(DownloadResource.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, download_id: uuid.UUID) -> Optional[DownloadResource]:
        stmt = select(DownloadResource).where(DownloadResource.id == download_id)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def create_download(self, download_in: DownloadResourceCreate, file_url: Optional[str], user_id: uuid.UUID) -> DownloadResource:
        # Extraemos metadata si existe (viene como dict porque lo pasamos como JSONB)
        db_download = DownloadResource(
            layer_id=download_in.layer_id,
            name=download_in.name,
            category=download_in.category,
            description=download_in.description,
            metadata_=download_in.metadata_,
            file_url=file_url,
            show_in_public=download_in.show_in_public,
            created_by=user_id
        )
        self.db.add(db_download)
        await self.db.commit()
        await self.db.refresh(db_download)
        return db_download

    async def update_download(self, download_id: uuid.UUID, update_data: dict) -> Optional[DownloadResource]:
        db_download = await self.get_by_id(download_id)
        if not db_download:
            return None
            
        for field, value in update_data.items():
            if value is not None:
                # Si el campo se llama "metadata" pero en db_download es "metadata_"
                field_name = "metadata_" if field == "metadata" else field
                setattr(db_download, field_name, value)
        
        await self.db.commit()
        await self.db.refresh(db_download)
        return db_download

    async def delete_download(self, download_id: uuid.UUID) -> bool:
        db_download = await self.get_by_id(download_id)
        if not db_download:
            return False
            
        await self.db.delete(db_download)
        await self.db.commit()
        return True
