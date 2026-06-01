import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class CartografiaGenerateRequest(BaseModel):
    layer_id: uuid.UUID
    secondary_layer_id: uuid.UUID | None = None
    title: str = Field(default="Carta cartografica digital", max_length=180)
    data_scope: Literal["all", "filtered"] = "all"
    filter_field: str | None = None
    filter_value: str | None = None
    attribute_fields: list[str] = Field(default_factory=list, max_length=24)
    output_format: Literal["pdf", "png", "geojson"] = "pdf"
    page_size: Literal["a4", "letter", "tabloid"] = "a4"
    orientation: Literal["portrait", "landscape"] = "landscape"


class CartografiaGeoJSONResponse(BaseModel):
    title: str
    layer_id: uuid.UUID
    layer_name: str
    feature_count: int
    attributes: list[str]
    filters: dict[str, Any]
    geojson: dict[str, Any]
