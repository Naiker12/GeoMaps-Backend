from sqlalchemy import Column, String, Boolean, DateTime, UUID
from app.infrastructure.database.session import Base
import uuid
from datetime import datetime, timezone

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4) # ID puede venir de Supabase o ser autogenerado
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    password_hash = Column(String, nullable=True) # Para usuarios creados por Admin
    avatar_url = Column(String, nullable=True)
    role = Column(String, default="user")
    provider = Column(String, default="google")
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<User(email={self.email}, role={self.role}, provider={self.provider})>"
