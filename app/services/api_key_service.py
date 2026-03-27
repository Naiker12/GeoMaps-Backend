import uuid
from typing import List, Optional, Tuple, Sequence, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.api_key import APIKey, APIKeyStatus, APIKeyRole, APIKeyVisibility
from app.repositories.api_key_repository import APIKeyRepository
from app.schemas.api_key import APIKeyCreate, APIKeyUpdate

class APIKeyService:
    def __init__(self, db: AsyncSession):
        self.repository = APIKeyRepository(db)

    async def create_api_key(
        self, 
        user_id: uuid.UUID, 
        api_key_in: APIKeyCreate,
        # Admin overrides
        assigned_user_id: Optional[uuid.UUID] = None
    ) -> Tuple[APIKey, str]:
        # Si assigned_user_id está presente, es que un Admin está asignando key a otro
        target_user_id = assigned_user_id or user_id
        
        return await self.repository.create_key(
            user_id=target_user_id,
            name=api_key_in.name,
            role=api_key_in.role,
            visibility=api_key_in.visibility,
            description=api_key_in.description,
            expires_at=api_key_in.expires_at,
            rate_limit_rpm=api_key_in.rate_limit_rpm
        )

    async def list_user_keys(self, user_id: uuid.UUID) -> Sequence[APIKey]:
        return await self.repository.get_by_user(user_id=user_id, active_only=False)

    async def revoke_api_key(self, key_id: uuid.UUID, user_id: uuid.UUID, is_admin: bool = False) -> Optional[APIKey]:
        db_obj = await self.repository.get(key_id)
        if not db_obj:
            return None
        
        # Security check: must be owner or admin
        if not is_admin and db_obj.user_id != user_id:
            return None
        
        from datetime import datetime
        update_data = {
            "status": APIKeyStatus.REVOKED,
            "revoked_at": datetime.now(),
            "revoked_by": user_id if is_admin else db_obj.user_id
        }
        
        return await self.repository.update(db_obj, update_data)

    async def delete_api_key(self, key_id: uuid.UUID, user_id: uuid.UUID, is_admin: bool = False) -> bool:
        db_obj = await self.repository.get(key_id)
        if not db_obj:
            return False
            
        # Security check: must be owner or admin
        if not is_admin and db_obj.user_id != user_id:
            return False
            
        return await self.repository.delete(db_obj)

    async def get_key_by_hash(self, key_hash: str) -> Optional[APIKey]:
        return await self.repository.get_by_hash(key_hash)

    async def list_admin_keys_paginated(self, **kwargs) -> Tuple[Sequence[APIKey], int]:
        return await self.repository.list_admin_keys(**kwargs)

    async def get_overview_stats(self) -> Dict[str, Any]:
        return await self.repository.get_stats_overview()

    async def get_user_stats_summary(self, user_id: uuid.UUID) -> Dict[str, Any]:
        return await self.repository.get_user_stats_summary(user_id)
        
    async def log_api_usage(self, **kwargs):
        return await self.repository.log_usage(**kwargs)

    async def check_daily_quota(self, user_id: uuid.UUID) -> bool:
        """Determina si el usuario tiene peticiones restantes hoy (Límite 10)."""
        return await self.repository.check_daily_quota(user_id)
