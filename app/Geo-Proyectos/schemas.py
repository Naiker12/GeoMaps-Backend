import uuid
from datetime import date, datetime
from typing import List, Optional, Any
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.db.models.project import ProjectStatus, InternalStatus, Currency
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

# --- Multimedia Schemas ---

class ProjectImageBase(BaseModel):
    url: str
    order_index: int = 0

class ProjectImageCreate(ProjectImageBase):
    pass

class ProjectImage(ProjectImageBase):
    id: uuid.UUID
    project_id: uuid.UUID
    class Config:
        from_attributes = True

class ProjectModel3DBase(BaseModel):
    url: str

class ProjectModel3DCreate(ProjectModel3DBase):
    pass

class ProjectModel3D(ProjectModel3DBase):
    id: uuid.UUID
    project_id: uuid.UUID
    class Config:
        from_attributes = True

# --- Domain Specific Schemas ---

class ProjectLocationBase(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    external_location_url: Optional[str] = None
    shapefile_url: Optional[str] = None

class ProjectLocation(ProjectLocationBase):
    id: uuid.UUID
    geometry: Optional[Any] = None

    @field_validator("geometry", mode="before")
    @classmethod
    def transform_geometry(cls, v):
        if v is None:
            return None
        
        # Caso 1: Es un WKBElement de GeoAlchemy2 (viene de la DB)
        if hasattr(v, "data") and hasattr(v, "srid"):
            try:
                return mapping(to_shape(v))
            except Exception:
                return str(v)
        
        # Caso 2: Es un objeto de Shapely (ya procesado)
        if hasattr(v, "geom_type"):
            return mapping(v)
            
        return v

    class Config:
        from_attributes = True

class ProjectMetricsBase(BaseModel):
    total_area: Optional[float] = None
    built_area: Optional[float] = None
    levels: Optional[int] = None
    total_units: Optional[int] = None
    lots: Optional[int] = None
    max_height: Optional[float] = None
    progress_percentage: int = Field(0, ge=0, le=100)
    estimated_delivery_date: Optional[date] = None
    custom_metrics: Optional[dict] = None
    registration_number: Optional[str] = None
    license_number: Optional[str] = None
    zoning: Optional[str] = None
    land_record: Optional[str] = None

class ProjectMetrics(ProjectMetricsBase):
    id: uuid.UUID
    class Config:
        from_attributes = True

class ProjectFinancialsBase(BaseModel):
    estimated_investment: Optional[float] = None
    average_unit_price: Optional[float] = None
    currency: Currency = Currency.COP

class ProjectFinancials(ProjectFinancialsBase):
    id: uuid.UUID
    class Config:
        from_attributes = True

class ProjectMapSettingsBase(BaseModel):
    map_color: Optional[str] = None
    map_opacity: int = Field(100, ge=0, le=100)
    show_label_on_map: bool = True
    custom_label_text: Optional[str] = None
    enable_3d_visualizer: bool = False

class ProjectMapSettings(ProjectMapSettingsBase):
    id: uuid.UUID
    class Config:
        from_attributes = True

class ProjectAdminSettingsBase(BaseModel):
    is_featured: bool = False
    is_publicly_visible: bool = True
    display_priority: int = 0

class ProjectAdminSettings(ProjectAdminSettingsBase):
    id: uuid.UUID
    class Config:
        from_attributes = True

# --- Inventario: Lotes ---

class ProjectLotBase(BaseModel):
    identifier: str
    nz_zone: Optional[str] = None
    floor_level: Optional[int] = None
    area_m2: Optional[float] = None
    status: str = "Disponible"
    price: Optional[float] = None
    custom_data: Optional[dict] = None

class ProjectLotCreate(ProjectLotBase):
    pass

class ProjectLotUpdate(BaseModel):
    identifier: Optional[str] = None
    nz_zone: Optional[str] = None
    floor_level: Optional[int] = None
    area_m2: Optional[float] = None
    status: Optional[str] = None
    price: Optional[float] = None
    custom_data: Optional[dict] = None

class ProjectLot(ProjectLotBase):
    id: uuid.UUID
    project_id: uuid.UUID
    geometry: Optional[Any] = None

    @field_validator("geometry", mode="before")
    @classmethod
    def transform_geometry(cls, v):
        if v is None: return None
        if hasattr(v, "data") and hasattr(v, "srid"):
            try: return mapping(to_shape(v))
            except Exception: return str(v)
        if hasattr(v, "geom_type"): return mapping(v)
        return v

    class Config:
        from_attributes = True

# --- Main Project Schemas ---

class ProjectBase(BaseModel):
    name: str = Field(..., max_length=150)
    description: str
    status: ProjectStatus = ProjectStatus.PLANNING
    developer_company: Optional[str] = None
    manager_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    glb_model_url: Optional[str] = None
    internal_status: InternalStatus = InternalStatus.ACTIVO

class ProjectCreate(ProjectBase):
    location: Optional[ProjectLocationBase] = None
    metrics: Optional[ProjectMetricsBase] = None
    financials: Optional[ProjectFinancialsBase] = None
    map_settings: Optional[ProjectMapSettingsBase] = None
    admin_settings: Optional[ProjectAdminSettingsBase] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    developer_company: Optional[str] = None
    manager_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    glb_model_url: Optional[str] = None
    internal_status: Optional[InternalStatus] = None
    
    location: Optional[ProjectLocationBase] = None
    metrics: Optional[ProjectMetricsBase] = None
    financials: Optional[ProjectFinancialsBase] = None
    map_settings: Optional[ProjectMapSettingsBase] = None
    admin_settings: Optional[ProjectAdminSettingsBase] = None

class Project(ProjectBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    
    location: Optional[ProjectLocation] = None
    metrics: Optional[ProjectMetrics] = None
    financials: Optional[ProjectFinancials] = None
    map_settings: Optional[ProjectMapSettings] = None
    admin_settings: Optional[ProjectAdminSettings] = None
    
    images: List[ProjectImage] = []
    models_3d: List[ProjectModel3D] = []
    lots: List[ProjectLot] = []

    class Config:
        from_attributes = True
