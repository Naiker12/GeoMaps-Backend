"""Repositorio compuesto que delega a los sub-repositorios.

Mantiene la interfaz idéntica al APIKeyRepository original
para compatibilidad total con el servicio y las rutas existentes.
"""
import uuid
from datetime import datetime
from typing import Optional, Sequence, Tuple, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.api_key import (
    APIKey, APIKeyRole, APIKeyVisibility, APIKeyUsageLog,
)
from app.repositories.api_key.key_repository import APIKeyCoreRepository
from app.repositories.api_key.usage_repository import APIKeyUsageRepository
from app.repositories.api_key.stats_repository import APIKeyStatsRepository
from app.repositories.api_key.settings_repository import APIKeySettingsRepository


class APIKeyRepository(APIKeyCoreRepository):
    """Fachada que compone CRUD + Usage + Stats + Settings en una sola clase.

    Hereda de APIKeyCoreRepository (que hereda de BaseRepository[APIKey]),
    y delega via composición a UsageRepository, StatsRepository y SettingsRepository.
    El service layer sigue llamando con la misma API — zero breaking changes.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self._usage = APIKeyUsageRepository(db)
        self._stats = APIKeyStatsRepository(db)
        self._settings = APIKeySettingsRepository(db)

    # ─── DELEGACIONES: Usage ──────────────────────────────────────────

    async def log_usage(self, **kwargs) -> APIKeyUsageLog:
        return await self._usage.log_usage(**kwargs)

    async def log_failed_attempt(self, **kwargs) -> APIKeyUsageLog:
        return await self._usage.log_failed_attempt(**kwargs)

    async def get_user_usage_count(self, user_id: uuid.UUID, days: int = 1) -> int:
        return await self._usage.get_user_usage_count(user_id, days)

    async def get_user_total_usage_count(self, user_id: uuid.UUID, days: int = 1) -> int:
        return await self._usage.get_user_total_usage_count(user_id, days)

    async def check_daily_quota(self, user_id: uuid.UUID) -> bool:
        return await self._usage.check_daily_quota(user_id)

    async def get_quota_status(self, user_id: uuid.UUID) -> dict:
        return await self._usage.get_quota_status(user_id)

    # ─── DELEGACIONES: Stats ──────────────────────────────────────────

    async def get_stats_overview(self) -> Dict[str, Any]:
        return await self._stats.get_stats_overview()

    async def get_user_stats_summary(self, user_id: uuid.UUID) -> Dict[str, Any]:
        return await self._stats.get_user_stats_summary(user_id)

    # ─── DELEGACIONES: Settings ──────────────────────────────────────────

    async def update_global_rate_limit(self, rpm: int, admin_id: uuid.UUID):
        return await self._settings.update_global_rate_limit(rpm, admin_id)

    async def toggle_global_traffic_pause(self, paused: bool, admin_id: uuid.UUID):
        return await self._settings.toggle_global_traffic_pause(paused, admin_id)

    async def update_global_ip_whitelist(self, ips: List[str], admin_id: uuid.UUID):
        return await self._settings.update_global_ip_whitelist(ips, admin_id)
