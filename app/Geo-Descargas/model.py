import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean, BigInteger, Integer, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.db.session import Base

class DownloadResource(Base):
    """Tabla principal de recursos de descarga."""
    __tablename__ = "download_resources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    layer_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("layers.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), default=list)
    
    # Storage - referencia al archivo en Supabase
    file_url: Mapped[Optional[str]] = mapped_column(Text)
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    file_format: Mapped[Optional[str]] = mapped_column(String(50))
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)

    # Metadatos calculados (se llenan tras el análisis del archivo)
    content_count: Mapped[Optional[int]] = mapped_column(Integer) # N° de features/filas
    geometry_type: Mapped[Optional[str]] = mapped_column(String(50)) # Point, Polygon, etc
    bbox: Mapped[Optional[str]] = mapped_column(Text) # Bounding box como string/WKT

    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default=dict)
    
    show_in_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relaciones
    layer = relationship("Layer", foreign_keys=[layer_id])
    creator = relationship("User", foreign_keys=[created_by])
