import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class LayerBase(BaseModel):
    name: str = Field(..., description="Nombre de la capa")
    description: Optional[str] = Field(None)
    category: Optional[str] = Field(None)
    source: Optional[str] = Field(None)
    visibility: str = Field(default="private")
    map_color: Optional[str] = Field("#3ECF8E")
    map_opacity: Optional[float] = Field(0.8)


class LayerCreate(LayerBase):
    pass


class LayerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    visibility: Optional[str] = None
    map_color: Optional[str] = None
    map_opacity: Optional[float] = None


# Schema público: sin file_url ni created_by
class LayerPublicResponse(LayerBase):
    id: uuid.UUID
    geometry_type: Optional[str]
    source_type: Optional[str]
    created_at: datetime
    updated_at: datetime


    class Config:
        from_attributes = True


# Schema completo: solo para usuarios autenticados
class LayerResponse(LayerPublicResponse):
    """Respuesta completa con file_url para usuarios autenticados."""
    file_url: Optional[str]
    created_by: Optional[uuid.UUID]


# GeoJSON
class FeatureGeometry(BaseModel):
    type: str
    coordinates: List[Any]


class FeatureSchema(BaseModel):
    type: str = "Feature"
    id: Optional[Any] = None
    geometry: FeatureGeometry
    properties: Dict[str, Any]


class FeatureCollectionSchema(BaseModel):
    type: str = "FeatureCollection"
    features: List[FeatureSchema]
