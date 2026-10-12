"""Repositorio de estadísticas y métricas para API Keys.

Contiene: get_stats_overview (admin), get_user_stats_summary (usuario).
"""
import uuid
from typing import Any, Dict

from sqlalchemy import select, func, and_, or_, case, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.limits import DAILY_API_KEY_LIMIT
from app.core.utils.datetime import get_utc_now

from app.db.models.api_key import (
    APIKey, APIKeyStatus, APIKeyUsageLog,
)


class APIKeyStatsRepository:
    """Consultas de métricas y estadísticas sobre api_key_usage_logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_stats_overview(self) -> Dict[str, Any]:
        """Métricas globales para el panel de administración."""
        # Totales generales desde la tabla api_keys
        total_req = (
            await self.db.execute(select(func.sum(APIKey.total_requests)))
        ).scalar() or 0

        total_tokens = (
            await self.db.execute(select(func.sum(APIKey.total_tokens)))
        ).scalar() or 0

        active_keys = (
            await self.db.execute(
                select(func.count(APIKey.id)).where(APIKey.status == APIKeyStatus.ACTIVE)
            )
        ).scalar() or 0

        revoked_keys = (
            await self.db.execute(
                select(func.count(APIKey.id)).where(APIKey.status == APIKeyStatus.REVOKED)
            )
        ).scalar() or 0

        # Contar totales desde los logs (más preciso que api_keys.total_requests)
        total_log_count = (
            await self.db.execute(select(func.count(APIKeyUsageLog.id)))
        ).scalar() or 0

        # Tasa de error
        error_count = (
            await self.db.execute(
                select(func.count(APIKeyUsageLog.id)).where(
                    APIKeyUsageLog.status_code >= 400
                )
            )
        ).scalar() or 0

        effective_total = max(total_log_count, int(total_req))
        error_rate = (error_count / effective_total * 100) if effective_total > 0 else 0.0

        # Latencia media
        avg_latency = (
            await self.db.execute(
                select(func.avg(APIKeyUsageLog.response_time_ms))
            )
        ).scalar() or 0.0

        # Tráfico por día (últimos 30 días)
        date_truncated = func.date_trunc("day", APIKeyUsageLog.requested_at).label("date")
        traffic_stmt = (
            select(
                date_truncated,
                func.count(APIKeyUsageLog.id).label("requests"),
                func.sum(
                    case((APIKeyUsageLog.status_code >= 400, 1), else_=0)
                ).label("errors"),
                func.sum(
                    case((APIKeyUsageLog.endpoint.like("%/layers%"), APIKeyUsageLog.tokens_used), else_=0)
                ).label("layers_tokens"),
                func.sum(
                    case(
                        (
                            or_(
                                APIKeyUsageLog.endpoint.like("%/downloads%"),
                                APIKeyUsageLog.endpoint.like("%/export%")
                            ),
                            APIKeyUsageLog.tokens_used
                        ),
                        else_=0
                    )
                ).label("downloads_tokens"),
                func.sum(APIKeyUsageLog.tokens_used).label("tokens"),
            )
            .where(
                APIKeyUsageLog.requested_at >= func.now() - text("interval '30 days'")
            )
            .group_by(date_truncated)
            .order_by(date_truncated)
        )

        traffic_result = await self.db.execute(traffic_stmt)
        raw_traffic = {r.date.date() if hasattr(r.date, 'date') else r.date: r for r in traffic_result}
        
        # Rellenar todos los días de los últimos 30 días
        traffic_by_day = []
        import datetime as dt
        today = get_utc_now().date()
        for i in range(29, -1, -1):
            target_date = today - dt.timedelta(days=i)
            row = raw_traffic.get(target_date)
            
            traffic_by_day.append({
                "date": target_date.strftime("%d %b"),
                "requests": row.requests if row else 0,
                "errors": int(row.errors) if row and row.errors else 0,
                "tokens": {
                    "layers": int(row.layers_tokens or 0) if row else 0,
                    "downloads": int(row.downloads_tokens or 0) if row else 0,
                    "total": int(row.tokens or 0) if row else 0,
                }
            })

        # Distribución de endpoints
        endpoint_stmt = (
            select(APIKeyUsageLog.endpoint, func.count(APIKeyUsageLog.id))
            .group_by(APIKeyUsageLog.endpoint)
            .order_by(func.count(APIKeyUsageLog.id).desc())
            .limit(5)
        )
        endpoint_result = await self.db.execute(endpoint_stmt)
        endpoint_distribution = {r[0]: r[1] for r in endpoint_result}

        return {
            "total_requests": max(int(total_req), total_log_count),
            "total_tokens": int(total_tokens),
            "active_keys": int(active_keys),
            "revoked_keys": int(revoked_keys),
            "error_count": int(error_count),
            "error_rate": round(float(error_rate), 2),
            "avg_latency_ms": round(float(avg_latency), 1),
            "traffic_by_day": traffic_by_day,
            "endpoint_distribution": endpoint_distribution,
            "token_distribution": {
                "layers": sum(t["tokens"]["layers"] for t in traffic_by_day),
                "downloads": sum(t["tokens"]["downloads"] for t in traffic_by_day),
            }
        }

    async def get_user_stats_summary(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """Resumen de estadísticas para el portal del usuario."""
        from app.repositories.api_key.usage_repository import APIKeyUsageRepository
        usage_repo = APIKeyUsageRepository(self.db)

        # Peticiones exitosas (las que cuentan para cuota)
        today_successful = await usage_repo.get_user_usage_count(user_id, 1)
        # Todas las peticiones (para métricas generales)
        today_all = await usage_repo.get_user_total_usage_count(user_id, 1)
        week_requests = await usage_repo.get_user_total_usage_count(user_id, 7)

        # Quota status detallado
        quota_status = await usage_repo.get_quota_status(user_id)

        # Errores del usuario
        error_count = (
            await self.db.execute(
                select(func.count(APIKeyUsageLog.id)).where(
                    and_(
                        APIKeyUsageLog.user_id == user_id,
                        APIKeyUsageLog.status_code >= 400,
                    )
                )
            )
        ).scalar() or 0

        # Latencia media del usuario
        avg_latency = (
            await self.db.execute(
                select(func.avg(APIKeyUsageLog.response_time_ms)).where(
                    APIKeyUsageLog.user_id == user_id
                )
            )
        ).scalar() or 0.0

        # Tráfico por día (últimos 20 días)
        date_truncated = func.date_trunc("day", APIKeyUsageLog.requested_at).label("date")
        traffic_stmt = (
            select(
                date_truncated,
                func.count(APIKeyUsageLog.id).label("requests"),
                func.sum(
                    case((APIKeyUsageLog.status_code >= 400, 1), else_=0)
                ).label("errors"),
                func.sum(
                    case((APIKeyUsageLog.endpoint.like("%/layers%"), APIKeyUsageLog.tokens_used), else_=0)
                ).label("layers_tokens"),
                func.sum(
                    case(
                        (
                            or_(
                                APIKeyUsageLog.endpoint.like("%/downloads%"),
                                APIKeyUsageLog.endpoint.like("%/export%")
                            ),
                            APIKeyUsageLog.tokens_used
                        ),
                        else_=0
                    )
                ).label("downloads_tokens"),
                func.sum(APIKeyUsageLog.tokens_used).label("total_tokens"),
            )
            .where(
                and_(
                    APIKeyUsageLog.user_id == user_id,
                    APIKeyUsageLog.requested_at >= func.now() - text("interval '20 days'"),
                )
            )
            .group_by(date_truncated)
            .order_by(date_truncated)
        )

        traffic_result = await self.db.execute(traffic_stmt)
        raw_traffic = {r.date.date() if hasattr(r.date, 'date') else r.date: r for r in traffic_result}
        
        # Rellenar todos los días de los últimos 20 días
        traffic_by_day = []
        import datetime as dt
        today = get_utc_now().date()
        for i in range(19, -1, -1):
            target_date = today - dt.timedelta(days=i)
            row = raw_traffic.get(target_date)
            
            traffic_by_day.append({
                "date": target_date.strftime("%d %b"),
                "requests": row.requests if row else 0,
                "errors": int(row.errors) if row and row.errors else 0,
                "tokens": {
                    "layers": int(row.layers_tokens or 0) if row else 0,
                    "downloads": int(row.downloads_tokens or 0) if row else 0,
                    "total": int(row.total_tokens or 0) if row else 0,
                }
            })

        daily_limit = DAILY_API_KEY_LIMIT

        return {
            "today_requests": today_successful,  # Solo exitosas (para cuota)
            "today_total": today_all,  # Todas (para métricas)
            "week_requests": week_requests,
            "error_count": int(error_count),
            "avg_latency_ms": round(float(avg_latency), 1),
            "total_tokens": sum(t["tokens"]["total"] for t in traffic_by_day),
            "monthly_usage": {
                "used": today_successful,
                "quota": daily_limit,
                "cycle_end": get_utc_now().strftime("%Y-%m-%d"),
            },
            "quota_status": quota_status,
            "token_distribution": {
                "layers": sum(t["tokens"]["layers"] for t in traffic_by_day),
                "downloads": sum(t["tokens"]["downloads"] for t in traffic_by_day),
            },
            "traffic_by_day": traffic_by_day,
        }
