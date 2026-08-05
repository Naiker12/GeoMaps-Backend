import uuid
from typing import Any, Sequence

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project_asset import ProjectAsset
from app.repositories.base_repository import BaseRepository


class ProjectAssetRepository(BaseRepository[ProjectAsset]):
    def __init__(self, db: AsyncSession):
        super().__init__(ProjectAsset, db)

    async def list_project_assets(
        self,
        project_id: uuid.UUID,
        kind: str | None = None,
        public_only: bool = False,
    ) -> Sequence[ProjectAsset]:
        stmt = select(ProjectAsset).where(ProjectAsset.project_id == project_id)
        if kind:
            stmt = stmt.where(ProjectAsset.kind == kind)
        if public_only:
            stmt = stmt.where(ProjectAsset.is_public == True)
        stmt = stmt.order_by(ProjectAsset.sort_order, ProjectAsset.created_at)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_project_asset(
        self,
        project_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> ProjectAsset | None:
        stmt = select(ProjectAsset).where(
            ProjectAsset.project_id == project_id,
            ProjectAsset.id == asset_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_project_asset(self, data: dict[str, Any]) -> ProjectAsset:
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata")
        asset = ProjectAsset(**data)
        self.db.add(asset)
        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    async def update_project_asset(
        self,
        asset: ProjectAsset,
        data: dict[str, Any],
    ) -> ProjectAsset:
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata")
        for key, value in data.items():
            if hasattr(asset, key):
                setattr(asset, key, value)
        self.db.add(asset)
        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    async def unset_primary_for_kind(
        self,
        project_id: uuid.UUID,
        kind: str,
        exclude_asset_id: uuid.UUID | None = None,
    ) -> None:
        stmt = (
            update(ProjectAsset)
            .where(ProjectAsset.project_id == project_id, ProjectAsset.kind == kind)
            .values(is_primary=False)
        )
        if exclude_asset_id:
            stmt = stmt.where(ProjectAsset.id != exclude_asset_id)
        await self.db.execute(stmt)

    async def get_renderable_models(
        self,
        project_id: uuid.UUID,
        public_only: bool = False,
    ) -> Sequence[ProjectAsset]:
        stmt = select(ProjectAsset).where(
            ProjectAsset.project_id == project_id,
            ProjectAsset.kind == "model_3d",
            ProjectAsset.extension.in_([".glb", ".gltf"]),
            or_(
                ProjectAsset.public_url.is_not(None),
                ProjectAsset.storage_path.is_not(None),
            ),
            ProjectAsset.conversion_status.in_(["not_required", "ready"]),
        )
        if public_only:
            stmt = stmt.where(ProjectAsset.is_public == True)
        stmt = stmt.order_by(ProjectAsset.is_primary.desc(), ProjectAsset.sort_order, ProjectAsset.created_at)
        result = await self.db.execute(stmt)
        return result.scalars().all()
