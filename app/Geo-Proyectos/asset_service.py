import uuid
from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.project_asset_repository import ProjectAssetRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.project_asset import ModelTransform, ProjectAssetResponse, ProjectAssetUpdate, RenderableModel
from app.services.footprints import footprint_service
from app.services.projects.asset_config import (
    ASSET_KIND_FOLDER,
    DEFAULT_ROLE_BY_KIND,
    SIGNED_URL_EXPIRES_IN_SECONDS,
    classify_asset_by_extension,
    file_extension,
    resolve_asset_bucket,
)
from app.services.projects.footprint_builder import ProjectFootprintBuilder
from app.services.projects.model_transform import resolve_model_transform
from app.services.storage import storage_service


class ProjectAssetService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = ProjectAssetRepository(db)
        self.project_repository = ProjectRepository(db)
        self.footprint_builder = ProjectFootprintBuilder(self.project_repository, self.repository)

    async def list_assets(
        self,
        project_id: uuid.UUID,
        kind: str | None = None,
        public_only: bool = False,
    ) -> list[ProjectAssetResponse]:
        assets = await self.repository.list_project_assets(project_id, kind=kind, public_only=public_only)
        return [await self._asset_response_with_access_url(asset) for asset in assets]

    async def upload_assets(
        self,
        project_id: uuid.UUID,
        files: list[UploadFile],
        kind: str | None = None,
        role: str | None = None,
        is_public: bool = True,
        is_primary: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> list[Any]:
        project = await self.project_repository.get_project_by_id(project_id)
        if not project:
            raise ValueError("Proyecto no encontrado")

        uploaded = []
        for index, file in enumerate(files):
            asset = await self.upload_asset(
                project_id=project_id,
                file=file,
                kind=kind,
                role=role,
                is_public=is_public,
                is_primary=is_primary and index == 0,
                metadata=metadata,
            )
            uploaded.append(asset)
        return uploaded

    async def upload_asset(
        self,
        project_id: uuid.UUID,
        file: UploadFile,
        kind: str | None = None,
        role: str | None = None,
        is_public: bool = True,
        is_primary: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        extension = file_extension(file.filename)
        resolved_kind = kind or self.classify_asset_by_extension(extension)
        bucket = self.resolve_asset_bucket(resolved_kind)
        folder = ASSET_KIND_FOLDER[resolved_kind]
        asset_id = uuid.uuid4()
        path_prefix = f"{project_id}/{folder}/{asset_id}"

        info = await storage_service.upload_file_to_bucket(
            file=file,
            bucket=bucket,
            path_prefix=path_prefix,
        )

        try:
            if is_primary:
                await self.repository.unset_primary_for_kind(project_id, resolved_kind)

            conversion_status = "pending" if resolved_kind == "bim_ifc" else "not_required"
            if resolved_kind == "model_3d":
                conversion_status = "not_required"

            data = {
                "id": asset_id,
                "project_id": project_id,
                "kind": resolved_kind,
                "role": role or DEFAULT_ROLE_BY_KIND.get(resolved_kind),
                "original_filename": info.original_filename,
                "storage_bucket": info.bucket,
                "storage_path": info.path,
                "public_url": info.public_url,
                "mime_type": info.mime_type,
                "file_size_bytes": info.file_size_bytes,
                "extension": info.extension,
                "conversion_status": conversion_status,
                "is_public": is_public,
                "is_primary": is_primary,
                "metadata": metadata,
            }
            return await self.repository.create_project_asset(data)
        except Exception:
            await storage_service.delete_file_by_path(info.bucket, info.path)
            raise

    async def update_asset(
        self,
        project_id: uuid.UUID,
        asset_id: uuid.UUID,
        asset_in: ProjectAssetUpdate,
    ) -> Any | None:
        asset = await self.repository.get_project_asset(project_id, asset_id)
        if not asset:
            return None

        data = asset_in.model_dump(exclude_unset=True)
        derived_from_asset_id = data.get("derived_from_asset_id")
        if derived_from_asset_id:
            source = await self.repository.get_project_asset(project_id, derived_from_asset_id)
            if not source or source.kind != "bim_ifc":
                raise ValueError("El asset fuente IFC no existe en este proyecto")
            if asset.kind != "model_3d":
                raise ValueError("Solo un modelo 3D puede asociarse a un IFC")

        if data.get("is_primary") is True:
            await self.repository.unset_primary_for_kind(project_id, asset.kind, exclude_asset_id=asset.id)
        return await self.repository.update_project_asset(asset, data)

    async def update_model_transform(
        self,
        project_id: uuid.UUID,
        asset_id: uuid.UUID,
        transform: ModelTransform,
    ) -> Any | None:
        asset = await self.repository.get_project_asset(project_id, asset_id)
        if not asset or asset.kind != "model_3d":
            return None
        data = {"transform": transform.model_dump(), "is_primary": True}
        await self.repository.unset_primary_for_kind(project_id, "model_3d", exclude_asset_id=asset.id)
        return await self.repository.update_project_asset(asset, data)

    async def delete_asset(self, project_id: uuid.UUID, asset_id: uuid.UUID) -> bool:
        asset = await self.repository.get_project_asset(project_id, asset_id)
        if not asset:
            return False
        if asset.storage_bucket and asset.storage_path:
            await storage_service.delete_file_by_path(asset.storage_bucket, asset.storage_path)
        return await self.repository.delete(asset_id)

    async def get_renderable_models(
        self,
        project_id: uuid.UUID,
        public_only: bool = False,
    ) -> list[RenderableModel]:
        project = await self.project_repository.get_project_by_id(project_id)
        if not project:
            return []

        assets = await self.repository.get_renderable_models(project_id, public_only=public_only)
        models: list[RenderableModel] = []
        for asset in assets:
            public_url = await self._resolve_access_url(asset)
            if not public_url:
                continue
            transform = resolve_model_transform(asset.transform, project)
            if not transform:
                continue
            models.append(
                RenderableModel(
                    asset_id=asset.id,
                    public_url=public_url,
                    original_filename=asset.original_filename,
                    is_primary=asset.is_primary,
                    transform=transform,
                )
            )
        return models

    async def get_project_footprint(self, project_id: uuid.UUID, public_only: bool = False) -> dict[str, Any] | None:
        return await self.footprint_builder.build(project_id, public_only=public_only)

    def classify_asset_by_extension(self, extension: str) -> str:
        return classify_asset_by_extension(extension)

    def resolve_asset_bucket(self, kind: str) -> str:
        return resolve_asset_bucket(kind)

    async def _asset_response_with_access_url(self, asset: Any) -> ProjectAssetResponse:
        response = ProjectAssetResponse.model_validate(asset)
        access_url = await self._resolve_access_url(asset)
        if access_url:
            return response.model_copy(update={"public_url": access_url})
        return response

    async def _resolve_access_url(self, asset: Any) -> str | None:
        bucket = getattr(asset, "storage_bucket", None)
        path = getattr(asset, "storage_path", None)
        if bucket and path:
            try:
                return await storage_service.create_signed_url(
                    bucket=bucket,
                    file_path=path,
                    expires_in=SIGNED_URL_EXPIRES_IN_SECONDS,
                )
            except RuntimeError:
                pass
        return getattr(asset, "public_url", None)
