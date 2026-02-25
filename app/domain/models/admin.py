from sqlalchemy import Column, String, Boolean, DateTime, UUID, text
from app.infrastructure.database.session import Base
import uuid
from app.core.utils.datetime import get_utc_now

class Admin(Base):
    __tablename__ = "admins"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_superadmin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), default=get_utc_now)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), default=get_utc_now, onupdate=get_utc_now)


    def __repr__(self):
        return f"<Admin(email={self.email}, is_superadmin={self.is_superadmin})>"
