import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

# Layer Schemas

class LayerBase(BaseModel):
    name: str = Field(..., description="Nombre de la capa")
    description: Optional[str] = Field(None, description="Descripción opcional")
    category: Optional[str] = Field(None, description="Categoría temática")
    source: Optional[str] = Field(None, description="Fuente de los datos (ej. IDECA, DANE, IGN...)")
    visibility: str = Field(default="private", description="Visibilidad de la capa: private, team, public")

class LayerCreate(LayerBase):
    pass

class LayerResponse(LayerBase):
    id: uuid.UUID
    geometry_type: Optional[str]
    source_type: Optional[str]
    file_url: Optional[str]
    created_by: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Feature Schemas (GeoJSON spec compatible)

class FeatureGeometry(BaseModel):
    type: str
    coordinates: List[Any]

class FeatureSchema(BaseModel):
    type: str = "Feature"
    geometry: FeatureGeometry
    properties: Dict[str, Any]

class FeatureCollectionSchema(BaseModel):
    type: str = "FeatureCollection"
    features: List[FeatureSchema]
