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
    label_field: str | None = None
    attribute_fields: list[str] = Field(default_factory=list, max_length=24)
    output_format: Literal["pdf", "png", "geojson"] = "pdf"
    page_size: Literal["a4", "letter", "tabloid"] = "a4"
    orientation: Literal["portrait", "landscape"] = "landscape"
    map_style: Literal["satellite", "streets", "topo", "none", "dark", "terrain", "watercolor"] = "satellite"
    border_style: Literal["none", "simple", "transparent", "fancy"] = "none"
    attributes_on_separate_page: bool = True
    primary_color: str | None = None
    secondary_color: str | None = None


class CartografiaGeoJSONResponse(BaseModel):
    title: str
    layer_id: uuid.UUID
    layer_name: str
    feature_count: int
    attributes: list[str]
    filters: dict[str, Any]
    geojson: dict[str, Any]
