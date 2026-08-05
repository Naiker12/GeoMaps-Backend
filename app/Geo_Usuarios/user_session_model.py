import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.shared.db.session import Base
from app.core.utils.datetime import get_utc_now

class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    session_type: Mapped[str] = mapped_column(String(50), nullable=False) # 'admin' o 'user'
    
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    
    login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=get_utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    logout_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    def is_valid(self):
        """Valida si la sesión es vigente comparando siempre en UTC aware."""
        now = get_utc_now()
        return self.logout_at is None and self.expires_at > now

    def __repr__(self):
        return f"<UserSession(user_id={self.user_id}, type={self.session_type})>"
