import secrets
import hashlib
import uuid
from datetime import datetime
from typing import Optional, Sequence, Tuple, List, Any, Dict
from sqlalchemy import select, update, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.api_key import (
    APIKey, APIKeyStatus, APIKeyRole, APIKeyVisibility,
    APIKeyUsageLog, APIKeyDailyStats, APIKeyIPWhitelist, APIKeyRateLimitConfig
)
from app.repositories.base_repository import BaseRepository

class APIKeyRepository(BaseRepository[APIKey]):
    def __init__(self, db: AsyncSession):
        super().__init__(APIKey, db)

    async def create_key(
        self, 
        user_id: uuid.UUID, 
        name: str = "Primary Key",
        role: APIKeyRole = APIKeyRole.CLIENT,
        visibility: APIKeyVisibility = APIKeyVisibility.PRIVATE,
        description: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        rate_limit_rpm: Optional[int] = None
    ) -> Tuple[APIKey, str]:
        """Generate a new API key, hash it, and save the hash."""
        raw_key = f"gm_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        
        db_obj = APIKey(
            user_id=user_id,
            name=name,
            key_prefix="gm_",
            key_hash=key_hash,
            hint=f"gm_...{raw_key[-4:]}",
            status=APIKeyStatus.ACTIVE,
            role=role,
            visibility=visibility,
            description=description,
            expires_at=expires_at,
            rate_limit_rpm=rate_limit_rpm
        )
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj, raw_key

    async def get_by_user(self, user_id: uuid.UUID, active_only: bool = True) -> Sequence[APIKey]:
        stmt = select(APIKey).where(APIKey.user_id == user_id)
        if active_only:
            stmt = stmt.where(APIKey.status == APIKeyStatus.ACTIVE)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_hash(self, key_hash: str) -> Optional[APIKey]:
        stmt = select(APIKey).where(APIKey.key_hash == key_hash, APIKey.status == APIKeyStatus.ACTIVE)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_admin_keys(
        self, 
        status: Optional[str] = None, 
        role: Optional[str] = None, 
        user_id: Optional[uuid.UUID] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50
    ) -> Tuple[Sequence[APIKey], int]:
        from sqlalchemy.orm import joinedload
        stmt = select(APIKey).options(joinedload(APIKey.user))
        
        if status:
            stmt = stmt.where(APIKey.status == status)
        if role:
            stmt = stmt.where(APIKey.role == role)
        if user_id:
            stmt = stmt.where(APIKey.user_id == user_id)
        if search:
            stmt = stmt.where(APIKey.name.ilike(f"%{search}%"))
            
        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.db.execute(count_stmt)
        total_count = total.scalar_one()
        
        # Paginate
        stmt = stmt.offset((page - 1) * limit).limit(limit).order_by(APIKey.created_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all(), total_count

    # ─── USAGE LOGS & METRICS ──────────────────────────────────────────────

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
        user_agent: Optional[str] = None
    ):
        log = APIKeyUsageLog(
            api_key_id=api_key_id,
            user_id=user_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            tokens_used=tokens_used,
            ip_address=ip_address,
            user_agent=user_agent
        )
        self.db.add(log)
        
        # Update totals in APIKey table
        stmt_key = (
            update(APIKey)
            .where(APIKey.id == api_key_id)
            .values(
                total_requests=APIKey.total_requests + 1,
                total_tokens=APIKey.total_tokens + tokens_used,
                last_used=func.now()
            )
        )
        
        # Update Daily Stats (Upsert-like for Postgres)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Primero intentamos buscar si existe para hoy
        stats_stmt = select(APIKeyDailyStats).where(
            and_(
                APIKeyDailyStats.api_key_id == api_key_id,
                APIKeyDailyStats.stat_date == today
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
                tokens_used=tokens_used
            )
            self.db.add(daily_stats)

        await self.db.execute(stmt_key)
        await self.db.commit()
        return log

    async def get_stats_overview(self) -> Dict[str, Any]:
        """Obtiene métricas reales para el panel de administración."""
        # Totales generales
        total_req_stmt = select(func.sum(APIKey.total_requests))
        total_req = (await self.db.execute(total_req_stmt)).scalar() or 0
        
        total_tokens_stmt = select(func.sum(APIKey.total_tokens))
        total_tokens = (await self.db.execute(total_tokens_stmt)).scalar() or 0

        active_keys_stmt = select(func.count(APIKey.id)).where(APIKey.status == APIKeyStatus.ACTIVE)
        active_keys = (await self.db.execute(active_keys_stmt)).scalar() or 0
        
        revoked_keys_stmt = select(func.count(APIKey.id)).where(APIKey.status == APIKeyStatus.REVOKED)
        revoked_keys = (await self.db.execute(revoked_keys_stmt)).scalar() or 0

        # Tasa de error (basada en logs de los últimos 30 días o total histórico)
        error_stmt = select(func.count(APIKeyUsageLog.id)).where(APIKeyUsageLog.status_code >= 400)
        error_count = (await self.db.execute(error_stmt)).scalar() or 0
        
        error_rate = (error_count / total_req * 100) if total_req > 0 else 0.0

        # Latencia media
        latency_stmt = select(func.avg(APIKeyUsageLog.response_time_ms))
        avg_latency = (await self.db.execute(latency_stmt)).scalar() or 0.0

        # Tráfico por día (últimos 7 días)
        date_truncated = func.date_trunc('day', APIKeyUsageLog.requested_at).label('date')
        traffic_stmt = (
            select(
                date_truncated,
                func.count(APIKeyUsageLog.id).label('requests'),
                func.sum(case({APIKeyUsageLog.status_code >= 400: 1}, else_=0)).label('errors'),
                func.sum(APIKeyUsageLog.tokens_used).label('tokens')
            )
            .group_by(date_truncated)
            .order_by(date_truncated)
            .limit(7)
        )
        
        traffic_result = await self.db.execute(traffic_stmt)
        traffic_by_day = [
            {
                "date": r.date, 
                "requests": r.requests or 0, 
                "errors": r.errors or 0, 
                "tokens": r.tokens or 0
            }
            for r in traffic_result
        ]

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
            "total_requests": int(total_req),
            "total_tokens": int(total_tokens),
            "active_keys": int(active_keys),
            "revoked_keys": int(revoked_keys),
            "error_rate": float(error_rate),
            "avg_latency_ms": float(avg_latency),
            "traffic_by_day": traffic_by_day,
            "endpoint_distribution": endpoint_distribution
        }

    async def get_user_usage_count(self, user_id: uuid.UUID, days: int = 1) -> int:
        """Cuenta peticiones de un usuario en un periodo determinado (p. ej. hoy)."""
        from sqlalchemy import text
        stmt = select(func.count(APIKeyUsageLog.id)).where(
            and_(
                APIKeyUsageLog.user_id == user_id,
                APIKeyUsageLog.requested_at >= func.now() - text(f"interval '{days} days'")
            )
        )
        count = (await self.db.execute(stmt)).scalar() or 0
        return int(count)

    async def get_user_stats_summary(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """Obtiene un resumen de estadísticas para el portal del usuario."""
        today_requests = await self.get_user_usage_count(user_id, 1)
        week_requests = await self.get_user_usage_count(user_id, 7)
        
        # Errores (4xx/5xx) del usuario
        error_stmt = select(func.count(APIKeyUsageLog.id)).where(
            and_(
                APIKeyUsageLog.user_id == user_id,
                APIKeyUsageLog.status_code >= 400
            )
        )
        error_count = (await self.db.execute(error_stmt)).scalar() or 0
        
        # Latencia media del usuario
        latency_stmt = select(func.avg(APIKeyUsageLog.response_time_ms)).where(APIKeyUsageLog.user_id == user_id)
        avg_latency = (await self.db.execute(latency_stmt)).scalar() or 0.0

        # Cuota diaria (10 peticiones)
        daily_limit = 10
        
        return {
            "today_requests": today_requests,
            "week_requests": week_requests,
            "error_count": error_count,
            "avg_latency_ms": float(avg_latency),
            "monthly_usage": { 
                "used": today_requests, # Usamos hoy para la barra de progreso de 10
                "quota": daily_limit, 
                "cycle_end": datetime.now().strftime("%Y-%m-%d") 
            },
            "traffic": [] 
        }

    async def check_daily_quota(self, user_id: uuid.UUID) -> bool:
        """Verifica si el usuario ha superado su límite estricto de 10 peticiones diarias."""
        # Consultamos el conteo en las últimas 24h
        today_requests = await self.get_user_usage_count(user_id, 1)
        return today_requests < 10
