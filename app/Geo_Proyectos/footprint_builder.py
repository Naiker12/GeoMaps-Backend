"""Builds map footprints from project CAD assets."""

from __future__ import annotations

import uuid
from typing import Any

from app.Geo_Proyectos.asset_repository import ProjectAssetRepository
from app.Geo_Proyectos.repository import ProjectRepository
from app.Geo_Footprints.service import footprint_service
from app.Geo_Proyectos.plan_dxf_selector import select_plan_dxf_asset
from app.Geo_Storage.service import storage_service


class ProjectFootprintBuilder:
    def __init__(
        self,
        project_repository: ProjectRepository,
        asset_repository: ProjectAssetRepository,
    ):
        self.project_repository = project_repository
        self.asset_repository = asset_repository

    async def build(self, project_id: uuid.UUID, public_only: bool = False) -> dict[str, Any] | None:
        project = await self.project_repository.get_project_by_id(project_id)
        if not project:
            return None

        assets = await self.asset_repository.list_project_assets(project_id, public_only=public_only)
        dxf_asset = select_plan_dxf_asset(assets)
        if not dxf_asset or not dxf_asset.storage_bucket or not dxf_asset.storage_path:
            return None

        lat = project.location.latitude if project.location else None
        lon = project.location.longitude if project.location else None
        if lat is None or lon is None:
            return None

        heading = await self._resolve_model_heading(project_id, public_only)
        data = await storage_service.download_file_by_path(dxf_asset.storage_bucket, dxf_asset.storage_path)
        return footprint_service.dxf_to_geojson(
            data=data,
            filename=dxf_asset.original_filename or "plan.dxf",
            center_lat=float(lat),
            center_lon=float(lon),
            heading=heading,
        )

    async def _resolve_model_heading(self, project_id: uuid.UUID, public_only: bool) -> float:
        model_assets = await self.asset_repository.get_renderable_models(project_id, public_only=public_only)
        for model_asset in model_assets:
            transform = model_asset.transform or {}
            return float(transform.get("heading") or 0)
        return 0.0
