"""Default and persisted 3D model transforms."""

from __future__ import annotations

from typing import Any

from app.schemas.project_asset import ModelTransform


def resolve_model_transform(transform: dict[str, Any] | None, project: Any) -> ModelTransform | None:
    if transform:
        data = dict(transform)
        data.setdefault("transform_source", "manual")
        return ModelTransform(**data)

    lat = project.location.latitude if project.location else None
    lon = project.location.longitude if project.location else None
    if lat is None or lon is None:
        return None

    return ModelTransform(
        latitude=float(lat),
        longitude=float(lon),
        altitude=0,
        elevation_mode="relative-to-ground",
        heading=0,
        tilt=0,
        roll=0,
        scale=1,
        height_m=12,
        anchor="origin",
        unit="meter",
        transform_source="default",
    )
