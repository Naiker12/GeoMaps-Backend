import enum
import uuid
from datetime import datetime, date
from typing import List, Optional, Any

from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, Numeric, Enum, Date, JSON, CheckConstraint, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry

from app.db.session import Base

class ProjectStatus(str, enum.Enum):
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class InternalStatus(str, enum.Enum):
    ACTIVO = "activo"
    ARCHIVADO = "archivado"

class Currency(str, enum.Enum):
    COP = "COP"
    USD = "USD"
    EUR = "EUR"

class Project(Base):
    """Tabla núcleo: Datos generales y administrativos básicos."""
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), 
        default=ProjectStatus.PLANNING,
        nullable=False
    )
    developer_company: Mapped[Optional[str]] = mapped_column(String(255))
    manager_name: Mapped[Optional[str]] = mapped_column(String(255))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    
    internal_status: Mapped[InternalStatus] = mapped_column(
        Enum(InternalStatus, name="internal_status"), 
        default=InternalStatus.ACTIVO,
        nullable=False
    )
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relaciones 1:1
    location: Mapped["ProjectLocation"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    metrics: Mapped["ProjectMetrics"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    financials: Mapped["ProjectFinancials"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    map_settings: Mapped["ProjectMapSettings"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    admin_settings: Mapped["ProjectAdminSettings"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")

    # Relaciones 1:N
    images: Mapped[List["ProjectImage"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    models_3d: Mapped[List["ProjectModel3D"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    lots: Mapped[List["ProjectLot"]] = relationship(back_populates="project", cascade="all, delete-orphan")

class ProjectLocation(Base):
    """Dominio: Ubicación y Geometría PostGIS."""
    __tablename__ = "project_locations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    geometry = mapped_column(Geometry("GEOMETRY", srid=4326), index=True)
    
    external_location_url: Mapped[Optional[str]] = mapped_column(String(500))
    shapefile_url: Mapped[Optional[str]] = mapped_column(String(500))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    
    project: Mapped["Project"] = relationship(back_populates="location")

class ProjectMetrics(Base):
    """Dominio: Métricas estructurales y de progreso."""
    __tablename__ = "project_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    
    total_area: Mapped[Optional[float]] = mapped_column(Numeric)
    built_area: Mapped[Optional[float]] = mapped_column(Numeric)
    levels: Mapped[Optional[int]] = mapped_column(Integer)
    total_units: Mapped[Optional[int]] = mapped_column(Integer)
    lots: Mapped[Optional[int]] = mapped_column(Integer)
    max_height: Mapped[Optional[float]] = mapped_column(Numeric)
    
    progress_percentage: Mapped[int] = mapped_column(Integer, CheckConstraint("progress_percentage >= 0 AND progress_percentage <= 100"), default=0, nullable=False)
    estimated_delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    
    custom_metrics: Mapped[Optional[dict]] = mapped_column(JSON)
    
    registration_number: Mapped[Optional[str]] = mapped_column(String(100))
    license_number: Mapped[Optional[str]] = mapped_column(String(100))
    zoning: Mapped[Optional[str]] = mapped_column(String(100))
    land_record: Mapped[Optional[str]] = mapped_column(String(100))

    project: Mapped["Project"] = relationship(back_populates="metrics")

class ProjectFinancials(Base):
    """Dominio: Información financiera."""
    __tablename__ = "project_financials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    
    estimated_investment: Mapped[Optional[float]] = mapped_column(Numeric)
    average_unit_price: Mapped[Optional[float]] = mapped_column(Numeric)
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency_type"), default=Currency.COP, nullable=False)
    
    project: Mapped["Project"] = relationship(back_populates="financials")

class ProjectMapSettings(Base):
    """Dominio: Configuración visual en el mapa."""
    __tablename__ = "project_map_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    
    map_color: Mapped[Optional[str]] = mapped_column(String(50))
    map_opacity: Mapped[int] = mapped_column(Integer, CheckConstraint("map_opacity >= 0 AND map_opacity <= 100"), default=100, nullable=False)
    show_label_on_map: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    custom_label_text: Mapped[Optional[str]] = mapped_column(String(255))
    enable_3d_visualizer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    project: Mapped["Project"] = relationship(back_populates="map_settings")

class ProjectAdminSettings(Base):
    """Dominio: Flags y prioridades administrativas."""
    __tablename__ = "project_admin_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_publicly_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    project: Mapped["Project"] = relationship(back_populates="admin_settings")

class ProjectImage(Base):
    """Multimedia: Imágenes del proyecto."""
    __tablename__ = "project_images"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="images")

class ProjectModel3D(Base):
    """Multimedia: Modelos 3D del proyecto."""
    __tablename__ = "project_models_3d"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="models_3d")

class ProjectLot(Base):
    """Inventario: Lotes individuales dentro de un proyecto."""
    __tablename__ = "project_lots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    
    identifier: Mapped[str] = mapped_column(String(50), nullable=False)
    nz_zone: Mapped[Optional[str]] = mapped_column(String(20))
    area_m2: Mapped[Optional[float]] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(String(50), default="Disponible") # Disponible, Vendido, Reservado, Proceso
    price: Mapped[Optional[float]] = mapped_column(Numeric)
    
    geometry: Mapped[Optional[Any]] = mapped_column(Geometry("GEOMETRY", srid=4326), index=True)
    custom_data: Mapped[Optional[dict]] = mapped_column(JSON)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    project: Mapped["Project"] = relationship(back_populates="lots")
