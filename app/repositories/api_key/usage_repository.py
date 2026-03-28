"""Repositorio de logging de uso de API Keys.

Contiene: log_usage, log_failed_attempt, check_daily_quota, get_user_usage_count.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.api_key import (
    APIKey, APIKeyUsageLog, APIKeyDailyStats,
)


class APIKeyUsageRepository:
    """Operaciones de logging y cuotas sobre api_key_usage_logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_usage(
        self,
        api_key_id: uuid.UUID,
        user_id: uuid.UUID,
        endpoint: str,
        method: str,
        status_code: int,
        response_time_ms: int,
        tokens_used: int = 0,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> APIKeyUsageLog:
        """Registra un uso exitoso de API Key y actualiza contadores."""
        log = APIKeyUsageLog(
            api_key_id=api_key_id,
            user_id=user_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            tokens_used=tokens_used,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.add(log)

        # Actualizar totales en la tabla api_keys
        stmt_key = (
            update(APIKey)
            .where(APIKey.id == api_key_id)
            .values(
                total_requests=APIKey.total_requests + 1,
                total_tokens=APIKey.total_tokens + tokens_used,
                last_used=func.now(),
            )
        )

        # Upsert de stats diarias
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        stats_stmt = select(APIKeyDailyStats).where(
            and_(
                APIKeyDailyStats.api_key_id == api_key_id,
                APIKeyDailyStats.stat_date == today,
            )
        )
        stats_result = await self.db.execute(stats_stmt)
        daily_stats = stats_result.scalar_one_or_none()

        if daily_stats:
            daily_stats.total_requests += 1
            if status_code < 400:
                daily_stats.success_requests += 1
            else:
                daily_stats.error_requests += 1
            daily_stats.tokens_used += tokens_used
        else:
            daily_stats = APIKeyDailyStats(
                api_key_id=api_key_id,
                user_id=user_id,
                stat_date=today,
                total_requests=1,
                success_requests=1 if status_code < 400 else 0,
                error_requests=1 if status_code >= 400 else 0,
                tokens_used=tokens_used,
            )
            self.db.add(daily_stats)

        await self.db.execute(stmt_key)
        await self.db.commit()
        return log

    async def log_failed_attempt(
        self,
        endpoint: str,
        method: str,
        status_code: int = 401,
        response_time_ms: int = 0,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        api_key_hint: Optional[str] = None,
    ) -> APIKeyUsageLog:
        """Registra un intento fallido (API Key inválida / revocada)."""
        log = APIKeyUsageLog(
            api_key_id=None,
            user_id=None,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            tokens_used=0,
            ip_address=ip_address,
            user_agent=user_agent,
            api_key_hint=api_key_hint,
        )
        self.db.add(log)
        await self.db.commit()
        return log

    async def get_user_usage_count(self, user_id: uuid.UUID, days: int = 1) -> int:
        """Cuenta peticiones de un usuario en los últimos N días."""
        stmt = select(func.count(APIKeyUsageLog.id)).where(
            and_(
                APIKeyUsageLog.user_id == user_id,
                APIKeyUsageLog.requested_at >= func.now() - text(f"interval '{days} days'"),
            )
        )
        count = (await self.db.execute(stmt)).scalar() or 0
        return int(count)

    async def check_daily_quota(self, user_id: uuid.UUID) -> bool:
        """Verifica si el usuario no ha superado el límite de 10 peticiones/día."""
        today_requests = await self.get_user_usage_count(user_id, 1)
        return today_requests < 10
