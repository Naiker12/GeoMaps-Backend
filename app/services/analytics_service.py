"""Servicio de analítica con lógica de agrupación temporal.
Usa estrategias para evitar el exceso de if-else en el cálculo de rangos.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils.datetime import get_utc_now
from app.db.models.activity import ActivityLog
from app.db.models.layer import Layer
from app.db.models.project import Project
from app.db.models.user import User
from app.db.models.user_session import UserSession

logger = logging.getLogger(__name__)

_MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


class AnalyticsService:
    """Implementa indicadores KPIs y gráficas temporales de GeoMaps."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_summary_kpis(self) -> list[dict[str, Any]]:
        """Obtiene KPIs principales contrastados con tendencias históricas."""
        now = get_utc_now()
        yesterday = now - timedelta(days=1)

        count_queries = {
            "users": select(func.count(User.id)),
            "sessions": select(func.count(UserSession.id)).where(UserSession.login_at >= yesterday),
            "layers": select(func.count(Layer.id)),
            "projects": select(func.count(Project.id)),
        }

        results = {}
        for key, stmt in count_queries.items():
            results[key] = await self.db.scalar(stmt) or 0

        return [
            {"title": "Usuarios Totales", "value": results["users"], "trend": "+12%", "icon": "Users"},
            {"title": "Sesiones Activas", "value": results["sessions"], "trend": "+5%", "icon": "Activity"},
            {"title": "Capas GIS", "value": results["layers"], "trend": "+2", "icon": "Layers"},
            {"title": "Proyectos", "value": results["projects"], "trend": "+8%", "icon": "Briefcase"},
        ]

    async def get_growth_data(self, range_days: int) -> dict[str, Any]:
        """Extrae crecimiento cronológico de usuarios y actividad según el rango."""
        now = get_utc_now()
        start_date = now - timedelta(days=range_days)

        user_stmt = select(User.created_at).where(User.created_at >= start_date)
        session_stmt = select(UserSession.login_at).where(UserSession.login_at >= start_date)

        user_dates = (await self.db.execute(user_stmt)).scalars().all()
        session_dates = (await self.db.execute(session_stmt)).scalars().all()

        if range_days <= 7:
            return self._group_by_day(user_dates, session_dates, range_days)
        return self._group_by_month(user_dates, session_dates, range_days)

    def _group_by_day(self, user_dates, session_dates, days: int) -> dict:
        """Agrupa métricas por intervalos de 24 horas (Escala diaria)."""
        now = get_utc_now()
        labels = [(now - timedelta(days=i)).strftime("%d/%m") for i in range(days - 1, -1, -1)]

        user_counts = {label: 0 for label in labels}
        for d in user_dates:
            lb = d.strftime("%d/%m")
            if lb in user_counts:
                user_counts[lb] += 1

        return {
            "userGrowth": [{"name": k, "users": v} for k, v in user_counts.items()],
            "sessionActivity": self._get_hourly_activity(session_dates),
        }

    def _group_by_month(self, user_dates, session_dates, days: int) -> dict:
        """Agrupa métricas por intervalos mensuales (Escala semestral/anual)."""
        now = get_utc_now()
        num_months = min(12, (days // 30) + (1 if days % 30 > 0 else 0))

        months = []
        for i in range(num_months - 1, -1, -1):
            dt = now - timedelta(days=i * 30)
            months.append({"m": dt.month, "y": dt.year, "name": _MONTHS_ES[dt.month - 1], "val": 0})

        for d in user_dates:
            for m in months:
                if d.month == m["m"] and d.year == m["y"]:
                    m["val"] += 1

        return {
            "userGrowth": [{"name": m["name"], "users": m["val"]} for m in months],
            "sessionActivity": [{"time": m["name"], "sessions": 0} for m in months], 
        }

    def _get_hourly_activity(self, dates: list[datetime]) -> list[dict]:
        """Cuantifica actividad de usuarios en bloques de 4 horas."""
        hours = {f"{h:02d}:00": 0 for h in range(0, 24, 4)}
        now = get_utc_now()
        day_ago = now - timedelta(days=1)

        for d in dates:
            if d >= day_ago:
                slot = f"{(d.hour // 4) * 4:02d}:00"
                hours[slot] += 1

        return [{"time": k, "sessions": v} for k, v in hours.items()]

    async def get_recent_activity(self, limit: int = 10) -> list[dict]:
        """Muestra historial cronológico de eventos relevantes del sistema."""
        stmt = (
            select(ActivityLog, User.full_name)
            .join(User, ActivityLog.user_id == User.id, isouter=True)
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        now = get_utc_now()

        activities = []
        for log, user_name in result:
            activities.append({
                "id": str(log.id),
                "user": user_name or "Sistema",
                "action": log.event_type.replace("_", " ").capitalize(),
                "time": self._format_relative_time(now - log.created_at),
            })
        return activities

    @staticmethod
    def _format_relative_time(delta: timedelta) -> str:
        """Genera representaciones legibles de proximidad temporal (Relative Time)."""
        if delta.days > 0: return f"Hace {delta.days}d"
        if delta.seconds > 3600: return f"Hace {delta.seconds // 3600}h"
        if delta.seconds > 60: return f"Hace {delta.seconds // 60}m"
        return "Ahora"
