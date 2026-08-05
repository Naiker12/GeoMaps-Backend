from sqlalchemy.ext.asyncio import AsyncSession
from app.shared.base_repository import BaseRepository
from app.Geo_ApiKeys.model import APIKey

class APIKeySettingsRepository(BaseRepository[APIKey]):
    def __init__(self, db: AsyncSession):
        super().__init__(APIKey, db)
    
    # Deprecated settings logic removed.