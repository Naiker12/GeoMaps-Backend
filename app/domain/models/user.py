from sqlalchemy import Column, String, Boolean, DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from app.infrastructure.database.session import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True)
    supabase_id = Column(UUID(as_uuid=True), unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    auth_provider = Column(String, nullable=True)
    role = Column(String, nullable=False, server_default="user") # 'super_admin', 'admin', 'user'
    is_active = Column(Boolean, server_default="true", default=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    last_login = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<User(email={self.email}, role={self.role})>"
