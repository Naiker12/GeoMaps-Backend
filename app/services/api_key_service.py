import uuid
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.api_key import APIKey, APIKeyStatus
from app.repositories.api_key_repository import APIKeyRepository
from app.schemas.api_key import APIKeyCreate, APIKeyUpdate

class APIKeyService:
    def __init__(self, db: AsyncSession):
        self.repository = APIKeyRepository(db)

    async def create_api_key(self, user_id: uuid.UUID, api_key_in: APIKeyCreate) -> Tuple[APIKey, str]:
        return await self.repository.create_key(user_id, api_key_in.name)

    async def list_user_keys(self, user_id: uuid.UUID) -> List[APIKey]:
        # Return all keys for the user (active or not, or just active based on UI need)
        # For now, let's use the repository method which filters for active
        return await self.repository.get_multi(user_id=user_id)

    async def revoke_api_key(self, key_id: uuid.UUID, user_id: uuid.UUID) -> Optional[APIKey]:
        db_obj = await self.repository.get(key_id)
        if not db_obj or db_obj.user_id != user_id:
            return None
        
        return await self.repository.update(db_obj, {"status": APIKeyStatus.REVOKED})

    async def get_key_by_hash(self, key_hash: str) -> Optional[APIKey]:
        return await self.repository.get_by_hash(key_hash)
