import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import AliasChoices, BaseModel, Field

AssetKind = Literal[
    "image",
    "model_3d",
    "bim_ifc",
    "document_pdf",
    "cad_dxf",
    "spatial_source",
    "thumbnail",
]

AssetRole = Literal[
    "cover",
    "gallery",
    "source",
    "renderable",
    "brochure",
    "plan",
    "legal",
    "technical",
]

ConversionStatus = Literal["not_required", "pending", "processing", "ready", "failed"]
ElevationMode = Literal["on-the-ground", "relative-to-ground", "absolute-height", "relative-to-scene"]


class ModelTransform(BaseModel):
    longitude: float
    latitude: float
    altitude: float = 0
    elevation_mode: ElevationMode = "relative-to-ground"
    heading: float = Field(0, ge=0, le=360)
    tilt: float = 0
    roll: float = 0
    scale: float = Field(1, gt=0)
    height_m: Optional[float] = Field(None, gt=0)
    width_m: Optional[float] = Field(None, gt=0)
    depth_m: Optional[float] = Field(None, gt=0)
    anchor: Literal["center", "origin", "bottom", "top", "relative"] = "origin"
    unit: Literal["meter"] = "meter"
    transform_source: Literal["default", "manual"] = "manual"


class ProjectAssetBase(BaseModel):
    kind: AssetKind
    role: Optional[AssetRole] = None
    conversion_status: ConversionStatus = "not_required"
    conversion_error: Optional[str] = None
    is_public: bool = True
    is_primary: bool = False
    sort_order: int = 0
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        validation_alias=AliasChoices("metadata_", "metadata"),
    )
    transform: Optional[dict[str, Any]] = None


class ProjectAssetCreate(ProjectAssetBase):
    original_filename: Optional[str] = None
    storage_bucket: Optional[str] = None
    storage_path: Optional[str] = None
    public_url: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    extension: Optional[str] = None
    derived_from_asset_id: Optional[uuid.UUID] = None


class ProjectAssetUpdate(BaseModel):
    role: Optional[AssetRole] = None
    derived_from_asset_id: Optional[uuid.UUID] = None
    conversion_status: Optional[ConversionStatus] = None
    conversion_error: Optional[str] = None
    is_public: Optional[bool] = None
    is_primary: Optional[bool] = None
    sort_order: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None
    transform: Optional[dict[str, Any]] = None


class ProjectModelTransformUpdate(BaseModel):
    transform: ModelTransform


class ProjectAssetResponse(ProjectAssetBase):
    id: uuid.UUID
    project_id: uuid.UUID
    original_filename: Optional[str] = None
    storage_bucket: Optional[str] = None
    storage_path: Optional[str] = None
    public_url: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    extension: Optional[str] = None
    derived_from_asset_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any):
        if hasattr(obj, "metadata_") and not isinstance(obj, dict):
            data = {
                key: getattr(obj, key)
                for key in (
                    "id",
                    "project_id",
                    "kind",
                    "role",
                    "original_filename",
                    "storage_bucket",
                    "storage_path",
                    "public_url",
                    "mime_type",
                    "file_size_bytes",
                    "extension",
                    "derived_from_asset_id",
                    "conversion_status",
                    "conversion_error",
                    "is_public",
                    "is_primary",
                    "sort_order",
                    "transform",
                    "created_at",
                    "updated_at",
                )
            }
            data["metadata"] = obj.metadata_
            return super().model_validate(data, *args, **kwargs)
        return super().model_validate(obj, *args, **kwargs)

    class Config:
        from_attributes = True


class RenderableModel(BaseModel):
    asset_id: uuid.UUID
    public_url: str
    original_filename: Optional[str] = None
    is_primary: bool = False
    transform: ModelTransform


class RenderableModelsResponse(BaseModel):
    project_id: uuid.UUID
    models: list[RenderableModel]
