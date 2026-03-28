import uuid
import enum
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, DateTime, func, ForeignKey, Integer, BigInteger, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import INET, CIDR, JSONB
from app.db.session import Base

class APIKeyStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"

class APIKeyRole(str, enum.Enum):
    CLIENT = "client"
    SERVICE = "service"
    ADMIN = "admin"
    DEVELOPER = "developer"

class APIKeyVisibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"

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

    # Nuevas Columnas (Fase 1)
    role: Mapped[APIKeyRole] = mapped_column(String(20), default=APIKeyRole.CLIENT)
    visibility: Mapped[APIKeyVisibility] = mapped_column(String(20), default=APIKeyVisibility.PRIVATE)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)
    rotated_from: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("api_keys.id"), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rate_limit_rpm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_requests: Mapped[int] = mapped_column(BigInteger, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="api_keys")
    revoked_by_user = relationship("User", foreign_keys=[revoked_by])
    
    usage_logs = relationship("APIKeyUsageLog", back_populates="api_key", cascade="all, delete-orphan")
    daily_stats = relationship("APIKeyDailyStats", back_populates="api_key", cascade="all, delete-orphan")
    ip_whitelist = relationship("APIKeyIPWhitelist", back_populates="api_key", cascade="all, delete-orphan")

    @property
    def user_email(self) -> Optional[str]:
        """Propiedad virtual para facilitar la serialización en el panel admin."""
        try:
            return self.user.email if self.user else None
        except Exception:
            return None

class APIKeyUsageLog(Base):
    __tablename__ = "api_key_usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"), index=True, nullable=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)

    endpoint: Mapped[str] = mapped_column(String(255), index=True)
    method: Mapped[str] = mapped_column(String(10))
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    response_time_ms: Mapped[int] = mapped_column(Integer)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_key_hint: Mapped[Optional[str]] = mapped_column(String(10), nullable=True) # Hint de la clave fallida

    # Relationships
    api_key = relationship("APIKey", back_populates="usage_logs")

class APIKeyIPWhitelist(Base):
    __tablename__ = "api_key_ip_whitelist"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"), index=True, nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    cidr_block: Mapped[str] = mapped_column(CIDR, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Relationships
    api_key = relationship("APIKey", back_populates="ip_whitelist")

class APIKeyRateLimitConfig(Base):
    __tablename__ = "api_key_rate_limit_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    
    rpm_limit: Mapped[int] = mapped_column(Integer, default=1000)
    daily_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    monthly_quota: Mapped[int] = mapped_column(Integer, default=500000)
    
    traffic_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)
    
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class APIKeyDailyStats(Base):
    __tablename__ = "api_key_daily_stats"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    stat_date: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    success_requests: Mapped[int] = mapped_column(Integer, default=0)
    error_requests: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(BigInteger, default=0)
    
    requests_by_endpoint: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    avg_response_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    p95_response_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    api_key = relationship("APIKey", back_populates="daily_stats")
