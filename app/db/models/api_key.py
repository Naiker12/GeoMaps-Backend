import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class APIKeyStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"

class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="Primary Key")
    key_prefix: Mapped[str] = mapped_column(String(10))
    key_hash: Mapped[str] = mapped_column(String(128), index=True, unique=True)
    hint: Mapped[str] = mapped_column(String(10)) 
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[APIKeyStatus] = mapped_column(String(20), default=APIKeyStatus.ACTIVE)

    # Relationships
    user = relationship("User", back_populates="api_keys")
