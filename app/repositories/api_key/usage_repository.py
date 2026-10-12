"""Repositorio de logging de uso de API Keys.

Contiene: log_usage, log_failed_attempt, check_daily_quota, get_user_usage_count.
"""
import uuid
from datetime import timedelta, timezone
from typing import Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from app.core.limits import DAILY_API_KEY_LIMIT
from app.core.utils.datetime import get_utc_now

from app.db.models.api_key import (
    APIKey, APIKeyUsageLog, APIKeyDailyStats,
)
from app.db.models.user import User


class APIKeyUsageRepository:
    """Operaciones de logging y cuotas sobre api_key_usage_logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def reserve_daily_quota(
        self, *, api_key_id: uuid.UUID, user_id: uuid.UUID,
        endpoint: str, method: str, ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> uuid.UUID | None:
        """Serializa admisiones por usuario, incluidas sus distintas API keys.

        El cupo cuenta desde la admisión durante 24 horas. Un resultado fallido
        lo libera; una reserva abandonada conserva el cupo hasta salir de la ventana.
        """
        result = await self.db.execute(select(User.id).where(User.id == user_id).with_for_update())
        if result.scalar_one_or_none() is None:
            await self.db.rollback()
            return None
        if not await self.check_daily_quota(user_id):
            await self.db.rollback()
            return None
        reservation_id = uuid.uuid4()
        self.db.add(APIKeyUsageLog(
            id=reservation_id, api_key_id=api_key_id, user_id=user_id,
            endpoint=endpoint, method=method, status_code=102, quota_pending=True,
            response_time_ms=0, tokens_used=0, ip_address=ip_address, user_agent=user_agent,
        ))
        await self.db.commit()
        return reservation_id

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
        reservation_id: uuid.UUID | None = None,
    ) -> APIKeyUsageLog | None:
        """Registra un uso exitoso de API Key y actualiza contadores."""
        if reservation_id is not None:
            result = await self.db.execute(
                update(APIKeyUsageLog).where(
                    APIKeyUsageLog.id == reservation_id,
                    APIKeyUsageLog.api_key_id == api_key_id,
                    APIKeyUsageLog.user_id == user_id,
                    APIKeyUsageLog.quota_pending.is_(True),
                ).values(
                    status_code=status_code, response_time_ms=response_time_ms,
                    tokens_used=tokens_used, quota_pending=False,
                ).returning(APIKeyUsageLog)
            )
            log = result.scalar_one_or_none()
            if log is None:
                # Una finalización repetida no debe sumar estadísticas otra vez.
                await self.db.commit()
                return None
        else:
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
        # stat_date es una columna histórica sin zona; guardar medianoche UTC.
        event_time = log.requested_at if reservation_id is not None else get_utc_now()
        today = event_time.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        stats_insert = insert(APIKeyDailyStats).values(
            id=uuid.uuid4(), api_key_id=api_key_id, user_id=user_id, stat_date=today,
            total_requests=1, success_requests=int(status_code < 400),
            error_requests=int(status_code >= 400), tokens_used=tokens_used,
            requests_by_endpoint={},
        )
        stats_upsert = stats_insert.on_conflict_do_update(
            index_elements=[APIKeyDailyStats.api_key_id, APIKeyDailyStats.stat_date],
            set_={
                "total_requests": APIKeyDailyStats.total_requests + stats_insert.excluded.total_requests,
                "success_requests": APIKeyDailyStats.success_requests + stats_insert.excluded.success_requests,
                "error_requests": APIKeyDailyStats.error_requests + stats_insert.excluded.error_requests,
                "tokens_used": APIKeyDailyStats.tokens_used + stats_insert.excluded.tokens_used,
            },
        )

        await self.db.execute(stmt_key)
        await self.db.execute(stats_upsert)
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
        """Cuenta resultados exitosos y reservas en curso en los últimos N días.
        Reservas pendientes usan status_code 102 hasta finalizar.
        """
        return await self._count_usage(user_id, days, successful_only=True)

    async def get_user_total_usage_count(self, user_id: uuid.UUID, days: int = 1) -> int:
        """Cuenta TODAS las peticiones de un usuario (exitosas + errores) para métricas."""
        return await self._count_usage(user_id, days, successful_only=False)

    async def _count_usage(self, user_id: uuid.UUID, days: int, *, successful_only: bool) -> int:
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
            raise ValueError("days debe ser un entero positivo")
        stmt = select(func.count(APIKeyUsageLog.id)).where(
            APIKeyUsageLog.user_id == user_id,
            APIKeyUsageLog.requested_at >= func.now() - timedelta(days=days),
        )
        if successful_only:
            stmt = stmt.where(APIKeyUsageLog.status_code < 400)
        count = (await self.db.execute(stmt)).scalar() or 0
        return int(count)

    async def check_daily_quota(self, user_id: uuid.UUID) -> bool:
        """Verifica si el usuario no ha superado el límite de 10 peticiones/día.
        Incluye peticiones admitidas en curso; fallidas finalizadas no cuentan.
        """
        today_requests = await self.get_user_usage_count(user_id, 1)
        return today_requests < DAILY_API_KEY_LIMIT

    async def get_quota_status(self, user_id: uuid.UUID) -> dict:
        """Retorna estado detallado de cuota para el frontend."""
        successful_today = await self.get_user_usage_count(user_id, 1)
        remaining = max(0, DAILY_API_KEY_LIMIT - successful_today)
        return {
            "used": successful_today,
            "limit": DAILY_API_KEY_LIMIT,
            "remaining": remaining,
            "is_warning": successful_today >= (DAILY_API_KEY_LIMIT - 2),
            "is_blocked": successful_today >= DAILY_API_KEY_LIMIT,
        }
