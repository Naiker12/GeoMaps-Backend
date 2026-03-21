import secrets
import hashlib
import uuid
from typing import Optional, Sequence, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.api_key import APIKey, APIKeyStatus
from app.repositories.base_repository import BaseRepository

class APIKeyRepository(BaseRepository[APIKey]):
    def __init__(self, db: AsyncSession):
        super().__init__(APIKey, db)

    async def create_key(self, user_id: uuid.UUID, name: str = "Primary Key") -> Tuple[APIKey, str]:
        """Generate a new API key, hash it, and save the hash."""
        raw_key = f"gm_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        
        db_obj = APIKey(
            user_id=user_id,
            name=name,
            key_prefix="gm_",
            key_hash=key_hash,
            hint=f"gm_...{raw_key[-4:]}",
            status=APIKeyStatus.ACTIVE
        )
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj, raw_key

    async def get_by_user(self, user_id: uuid.UUID) -> Sequence[APIKey]:
        stmt = select(APIKey).where(APIKey.user_id == user_id, APIKey.status == APIKeyStatus.ACTIVE)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_hash(self, key_hash: str) -> Optional[APIKey]:
        stmt = select(APIKey).where(APIKey.key_hash == key_hash, APIKey.status == APIKeyStatus.ACTIVE)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
