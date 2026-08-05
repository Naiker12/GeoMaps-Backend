import enum
import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy import String, Text, DateTime, ForeignKey, Enum, BigInteger, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry

from app.db.session import Base

class VisibilityEnum(str, enum.Enum):
    PRIVATE = "PRIVATE"
    TEAM = "TEAM"
    PUBLIC = "PUBLIC"

class Layer(Base):
    """Tabla principal de metadatos de las capas GIS."""
    __tablename__ = "layers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    subcategory: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(255))
    geometry_type: Mapped[Optional[str]] = mapped_column(String(50)) # POINT, LINESTRING, POLYGON, MULTI*
    source_type: Mapped[Optional[str]] = mapped_column(String(50)) # geojson, shapefile
    visibility: Mapped[VisibilityEnum] = mapped_column(
        Enum(VisibilityEnum, name="layer_visibility"),
        default=VisibilityEnum.PRIVATE,
        nullable=False
    )
    map_color: Mapped[Optional[str]] = mapped_column(String(50), default="#3ECF8E")
    map_opacity: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    file_url: Mapped[Optional[str]] = mapped_column(Text)
    stats_config: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)          # Configuración de gráficas y KPIs
    feature_card_config: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)   # Configuración de ficha del punto
    symbology: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)             # Configuración de simbología visual (single, categorized, graduated)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relaciones
    features: Mapped[list["LayerFeature"]] = relationship(back_populates="layer", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])


class LayerFeature(Base):
    """Tabla que contiene las geometrías individuales de cada capa."""
    __tablename__ = "layer_features"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    layer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("layers.id", ondelete="CASCADE"), nullable=False, index=True)
    
    display_name: Mapped[Optional[str]] = mapped_column(Text)  # Nombre canónico extraído por el normalizador
    properties: Mapped[Optional[dict]] = mapped_column(JSONB) # Metadata original del archivo GIS
    geom: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=False, index=True) # Index automatizado con GiST
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    layer: Mapped["Layer"] = relationship(back_populates="features")
