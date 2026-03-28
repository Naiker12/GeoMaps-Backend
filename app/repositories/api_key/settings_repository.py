import uuid
from datetime import datetime
from typing import Optional, List, Sequence
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.api_key import APIKeyRateLimitConfig, APIKeyIPWhitelist
from app.repositories.base_repository import BaseRepository

class APIKeySettingsRepository(BaseRepository[APIKeyRateLimitConfig]):
    def __init__(self, db: AsyncSession):
        super().__init__(APIKeyRateLimitConfig, db)

    async def get_or_create_global_config(self) -> APIKeyRateLimitConfig:
        """Obtiene la configuración global (asociada a un ID nulo o un UUID fijo de sistema)."""
        # Usaremos un UUID fijo para la configuración GLOBAL del sistema
        SYSTEM_CONFIG_ID = uuid.UUID('00000000-0000-0000-0000-000000000000')
        
        stmt = select(APIKeyRateLimitConfig).where(APIKeyRateLimitConfig.user_id == SYSTEM_CONFIG_ID)
        result = await self.db.execute(stmt)
        db_obj = result.scalar_one_or_none()
        
        if not db_obj:
            db_obj = APIKeyRateLimitConfig(
                user_id=SYSTEM_CONFIG_ID,
                rpm_limit=1000,
                monthly_quota=1000000,
                traffic_paused=False
            )
            self.db.add(db_obj)
            await self.db.commit()
            await self.db.refresh(db_obj)
            
        return db_obj

    async def update_global_rate_limit(self, rpm: int, admin_id: uuid.UUID) -> APIKeyRateLimitConfig:
        config = await self.get_or_create_global_config()
        config.rpm_limit = rpm
        config.updated_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def toggle_global_traffic_pause(self, paused: bool, admin_id: uuid.UUID) -> APIKeyRateLimitConfig:
        config = await self.get_or_create_global_config()
        config.traffic_paused = paused
        config.paused_at = datetime.now() if paused else None
        config.paused_by = admin_id
        config.updated_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def update_global_ip_whitelist(self, ips: List[str], admin_id: uuid.UUID):
        """Actualiza la lista blanca de IPs GLOBAL (user_id sistema)."""
        SYSTEM_ID = uuid.UUID('00000000-0000-0000-0000-000000000000')
        
        # 1. Eliminar anteriores
        del_stmt = delete(APIKeyIPWhitelist).where(APIKeyIPWhitelist.user_id == SYSTEM_ID, APIKeyIPWhitelist.api_key_id == None)
        await self.db.execute(del_stmt)
        
        # 2. Insertar nuevas
        new_entries = [
            APIKeyIPWhitelist(
                user_id=SYSTEM_ID,
                api_key_id=None,
                cidr_block=ip,
                label="Global Admin Whitelist",
                created_by=admin_id
            ) for ip in ips
        ]
        self.db.add_all(new_entries)
        await self.db.commit()
        return ips
