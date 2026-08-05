import json
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.Geo_Usuarios.model import User
from app.shared.db.session import get_db
from app.Geo_Proyectos.asset_schemas import (
    ProjectAssetResponse,
    ProjectAssetUpdate,
    ProjectModelTransformUpdate,
    RenderableModelsResponse,
)
from app.Geo_Proyectos.schemas import (
    Project,
    ProjectCreate,
    ProjectImage,
    ProjectLot,
    ProjectLotUpdate,
    ProjectModel3D,
    ProjectUpdate,
)
from app.Geo_Proyectos.asset_service import ProjectAssetService
from app.Geo_Proyectos.service import ProjectService

router = APIRouter()


@router.post("/", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user),
):
    return await service.create_project(project_in)


@router.get("/", response_model=List[Project])
async def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_active_user),
):
    return await service.get_projects(skip=skip, limit=limit)


@router.get("/public", response_model=List[Project])
async def list_public_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: ProjectService = Depends(deps.get_project_service),
    current_user: Optional[User] = Depends(deps.get_current_user_optional),
):
    return await service.get_projects(skip=skip, limit=limit, only_public=True)


@router.get("/{id}", response_model=Project)
async def get_project(
    id: uuid.UUID,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: Optional[User] = Depends(deps.get_current_user_optional),
):
    """
    Obtiene un proyecto por ID. Permite acceso público si el proyecto es visible.
    """
    project = await service.get_project_by_id(id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    # Validar visibilidad si el usuario no es admin o dueño
    # (Esto se debería manejar dentro del servicio, pero por ahora simplificamos)
    if current_user is None and not (
        project.admin_settings and project.admin_settings.is_publicly_visible
    ):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    return project


@router.put("/{id}", response_model=Project)
async def update_project(
    id: uuid.UUID,
    project_in: ProjectUpdate,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user),
):
    return await service.update_project(id, project_in)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    id: uuid.UUID,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user),
):
    await service.delete_project(id)


@router.get("/{id}/assets", response_model=List[ProjectAssetResponse])
async def list_project_assets(
    id: uuid.UUID,
    kind: Optional[str] = Query(None),
    service: ProjectService = Depends(deps.get_project_service),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional),
):
    project = await service.get_project_by_id(id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    public_only = current_user is None
    if public_only and not (
        project.admin_settings and project.admin_settings.is_publicly_visible
    ):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    asset_service = ProjectAssetService(db)
    return await asset_service.list_assets(id, kind=kind, public_only=public_only)


@router.post("/{id}/assets", response_model=List[ProjectAssetResponse])
async def upload_project_assets(
    id: uuid.UUID,
    files: List[UploadFile] = File(...),
    kind: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    is_public: bool = Form(True),
    is_primary: bool = Form(False),
    metadata: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_admin_user),
):
    try:
        parsed_metadata = json.loads(metadata) if metadata else None
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="metadata debe ser JSON valido") from exc

    asset_service = ProjectAssetService(db)
    try:
        return await asset_service.upload_assets(
            project_id=id,
            files=files,
            kind=kind,
            role=role,
            is_public=is_public,
            is_primary=is_primary,
            metadata=parsed_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{id}/assets/{asset_id}", response_model=ProjectAssetResponse)
async def update_project_asset(
    id: uuid.UUID,
    asset_id: uuid.UUID,
    asset_in: ProjectAssetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_admin_user),
):
    asset_service = ProjectAssetService(db)
    try:
        asset = await asset_service.update_asset(id, asset_id, asset_in)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not asset:
        raise HTTPException(status_code=404, detail="Asset no encontrado")
    return asset


@router.delete("/{id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_asset(
    id: uuid.UUID,
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_admin_user),
):
    asset_service = ProjectAssetService(db)
    success = await asset_service.delete_asset(id, asset_id)
    if not success:
        raise HTTPException(status_code=404, detail="Asset no encontrado")
    return None


@router.get("/{id}/models/renderable", response_model=RenderableModelsResponse)
async def get_renderable_project_models(
    id: uuid.UUID,
    service: ProjectService = Depends(deps.get_project_service),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional),
):
    project = await service.get_project_by_id(id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    public_only = current_user is None
    if public_only and not (
        project.admin_settings and project.admin_settings.is_publicly_visible
    ):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    asset_service = ProjectAssetService(db)
    models = await asset_service.get_renderable_models(id, public_only=public_only)
    return {"project_id": id, "models": models}


@router.get("/{id}/footprint")
async def get_project_footprint(
    id: uuid.UUID,
    service: ProjectService = Depends(deps.get_project_service),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional),
):
    project = await service.get_project_by_id(id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    public_only = current_user is None
    if public_only and not (
        project.admin_settings and project.admin_settings.is_publicly_visible
    ):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    asset_service = ProjectAssetService(db)
    footprint = await asset_service.get_project_footprint(id, public_only=public_only)
    if not footprint:
        raise HTTPException(status_code=404, detail="Footprint no disponible")
    return footprint


@router.patch("/{id}/models/{asset_id}/transform", response_model=ProjectAssetResponse)
async def update_project_model_transform(
    id: uuid.UUID,
    asset_id: uuid.UUID,
    transform_in: ProjectModelTransformUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_admin_user),
):
    asset_service = ProjectAssetService(db)
    asset = await asset_service.update_model_transform(id, asset_id, transform_in.transform)
    if not asset:
        raise HTTPException(status_code=404, detail="Modelo 3D no encontrado")
    return asset


@router.post("/{id}/images", response_model=List[ProjectImage])
async def upload_images(
    id: uuid.UUID,
    files: List[UploadFile] = File(...),
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user),
):
    return await service.add_project_images(id, files)


@router.post("/{id}/models", response_model=List[ProjectModel3D])
async def upload_models(
    id: uuid.UUID,
    files: List[UploadFile] = File(...),
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user),
):
    return await service.add_project_models(id, files)


@router.post("/{id}/shapefile", response_model=Project)
async def upload_shapefile(
    id: uuid.UUID,
    files: List[UploadFile] = File(...),
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user),
):
    try:
        return await service.upload_shapefile(id, files)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{id}/lots/geojson")
async def get_project_lots_geojson(
    id: uuid.UUID,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: Optional[User] = Depends(deps.get_current_user_optional),
):
    """
    Retorna los lotes de un proyecto como FeatureCollection GeoJSON.
    Endpoint público — útil para pintar capas vectoriales en el mapa frontend.
    """
    project = await service.get_project_by_id(id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    if current_user is None and not (
        project.admin_settings and project.admin_settings.is_publicly_visible
    ):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return await service.get_lots_geojson(id)


@router.put("/{id}/lots/{lot_id}", response_model=ProjectLot)
async def update_project_lot(
    id: uuid.UUID,
    lot_id: uuid.UUID,
    lot_in: ProjectLotUpdate,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user),
):
    """Actualiza la información (precio, estado, etc.) de un lote específico."""
    lot = await service.update_lot(lot_id, lot_in)
    if not lot:
        raise HTTPException(status_code=404, detail="Lote no encontrado")
    return lot
