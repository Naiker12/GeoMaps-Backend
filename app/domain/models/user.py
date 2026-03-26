from sqlalchemy import Column, String, Boolean, DateTime, text, Enum
from sqlalchemy.dialects.postgresql import UUID
import enum

import uuid
from app.db.session import Base

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"
    USER = "USER"

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supabase_id = Column(UUID(as_uuid=True), unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    bio = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    auth_provider = Column(String, nullable=True)
    role = Column(Enum(UserRole, name="user_role"), nullable=False, server_default="USER")
    is_active = Column(Boolean, server_default="true", default=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    last_login = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<User(email={self.email}, role={self.role})>"
