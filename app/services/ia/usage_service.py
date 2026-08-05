from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from typing import Dict, Any
from uuid import UUID
from app.shared.core.config import settings

class UsageService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.LIMIT = settings.IA_USAGE_LIMIT
        self.WINDOW_HOURS = settings.IA_USAGE_WINDOW_HOURS

    async def get_user_usage(self, user_id: UUID) -> Dict[str, Any]:
        """
        Calcula el uso de IA del usuario en la ventana de tiempo definida.
        """
        # Contar mensajes exitosos en las últimas 4 horas
        stmt = text("""
            SELECT COUNT(*) 
            FROM ia_audit_logs 
            WHERE user_id = :uid 
              AND status = 'success' 
              AND created_at >= NOW() - INTERVAL '1 hour' * :window
        """)
        
        result = await self.db.execute(stmt, {
            "uid": str(user_id), 
            "window": self.WINDOW_HOURS
        })
        count = result.scalar() or 0

        is_blocked = count >= self.LIMIT
        remaining_seconds = 0
        next_reset = None

        if is_blocked:
            # Encontrar el mensaje más antiguo dentro de la ventana que causará 
            # que el contador baje del límite permitido.
            reset_stmt = text("""
                SELECT created_at 
                FROM ia_audit_logs 
                WHERE user_id = :uid 
                  AND status = 'success' 
                  AND created_at >= NOW() - INTERVAL '1 hour' * :window
                ORDER BY created_at ASC
                LIMIT 1
            """)
            reset_res = await self.db.execute(reset_stmt, {
                "uid": str(user_id), 
                "window": self.WINDOW_HOURS
            })
            oldest_msg_time = reset_res.scalar()
            
            if oldest_msg_time:
                # El reset ocurre tras cumplirse la ventana desde el mensaje más antiguo
                next_reset = oldest_msg_time + timedelta(hours=self.WINDOW_HOURS)
                remaining_seconds = max(0, int((next_reset - datetime.now(next_reset.tzinfo)).total_seconds()))

        return {
            "current": count,
            "limit": self.LIMIT,
            "is_blocked": is_blocked,
            "remaining_seconds": remaining_seconds,
            "next_reset": next_reset
        }
