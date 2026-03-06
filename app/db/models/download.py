import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

class DownloadResource(Base):
    """Tabla principal de recursos de descarga."""
    __tablename__ = "download_resources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    layer_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("layers.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default=dict) # info adiccional (isNew, isPopular, etc)
    file_url: Mapped[Optional[str]] = mapped_column(Text)
    show_in_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relaciones
    layer = relationship("Layer", foreign_keys=[layer_id])
    creator = relationship("User", foreign_keys=[created_by])
