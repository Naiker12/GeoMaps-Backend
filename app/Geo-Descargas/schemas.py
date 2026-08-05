import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

# Download Schemas

class DownloadResourceBase(BaseModel):
    layer_id: Optional[uuid.UUID] = Field(None, description="ID de la capa GIS asociada si la hay")
    name: str = Field(..., description="Nombre comercial del recurso")
    category: str = Field(..., description="Categoría temática del recurso")
    description: Optional[str] = Field(None, description="Descripción del contenido del recurso")
    tags: List[str] = Field(default_factory=list, description="Etiquetas de búsqueda")
    metadata_: Optional[Dict[str, Any]] = Field(default_factory=dict, validation_alias="metadata_", serialization_alias="metadata", description="Metadatos adicionales")
    file_url: Optional[str] = Field(None, description="URL pública del archivo")
    file_path: Optional[str] = Field(None, description="Path interno en storage")
    file_format: Optional[str] = Field(None, description="Extensión del archivo (geojson, shp, etc)")
    file_size_bytes: Optional[int] = Field(None, description="Tamaño real en bytes")
    content_count: Optional[int] = Field(None, description="Número de registros o features")
    geometry_type: Optional[str] = Field(None, description="Tipo de geometría si aplica")
    bbox: Optional[str] = Field(None, description="Bounding box")
    show_in_public: bool = Field(default=True, description="Indica si se mostrará en el portal público")
    is_published: bool = Field(default=False, description="Estado de publicación")

class DownloadResourceCreate(DownloadResourceBase):
    pass

class DownloadResourceUpdate(BaseModel):
    layer_id: Optional[uuid.UUID] = None
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata_: Optional[Dict[str, Any]] = Field(None, validation_alias="metadata_", serialization_alias="metadata")
    file_url: Optional[str] = None
    show_in_public: Optional[bool] = None
    is_published: Optional[bool] = None

class DownloadResourceResponse(DownloadResourceBase):
    id: uuid.UUID
    created_by: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
