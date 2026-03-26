from sqlalchemy import Column, String, DateTime, UUID, text
from app.db.session import Base
import uuid
from app.core.utils.datetime import get_utc_now

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    session_type = Column(String, nullable=False) # 'admin' o 'user'
    
    user_agent = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    
    # Control de tiempo con Timezone obligatorio
    login_at = Column(DateTime(timezone=True), server_default=text("now()"), default=get_utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    logout_at = Column(DateTime(timezone=True), nullable=True)
    
    def is_valid(self):
        """Valida si la sesión es vigente comparando siempre en UTC aware."""
        now = get_utc_now()
        return self.logout_at is None and self.expires_at > now

    def __repr__(self):
        return f"<UserSession(user_id={self.user_id}, type={self.session_type}, valid={self.is_valid()})>"

