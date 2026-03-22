from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.utils.datetime import get_utc_now
from app.db.models.activity import ActivityLog
from app.db.models.user import User
from app.db.models.user_session import UserSession
from .utils import parse_ua, format_relative_time

class ActivityAnalytics:
    """Consolidación de bitácoras de actividad y sesiones de administradores."""
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_recent(self, limit: int = 50) -> list[dict]:
        """Registro cronológico de actividad reciente."""
        now = get_utc_now()
        activities = []
        stmt = (
            select(ActivityLog, User.full_name)
            .outerjoin(User, ActivityLog.user_id == User.id)
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
        )
        logs = (await self.db.execute(stmt)).all()
        if logs:
            for log, user_name in logs:
                device = parse_ua(log.metadata_.get("user_agent"))
                activities.append({
                    "id": str(log.id),
                    "user": user_name or "Sistema",
                    "device": device,
                    "action": log.event_type.replace("_", " ").capitalize(),
                    "target": log.metadata_.get("target", "N/A"),
                    "time": format_relative_time(now - log.created_at),
                    "status": log.metadata_.get("status", "success")
                })
        
        # Fallback a sesiones si no hay suficientes logs
        if len(activities) < limit:
            remaining = limit - len(activities)
            session_stmt = (
                select(UserSession, User.full_name)
                .join(User, UserSession.user_id == User.id)
                .order_by(UserSession.login_at.desc())
                .limit(remaining)
            )
            sessions = (await self.db.execute(session_stmt)).all()
            for session, user_name in sessions:
                activities.append({
                    "id": str(session.id),
                    "user": user_name,
                    "device": parse_ua(session.user_agent),
                    "action": "Inicio de sesión",
                    "target": f"IP: {session.ip_address or 'vocal'}",
                    "time": format_relative_time(now - session.login_at),
                    "status": "success"
                })
        return activities
