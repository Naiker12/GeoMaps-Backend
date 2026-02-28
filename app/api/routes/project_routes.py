from typing import List, Any
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, status, Query
from app.api import deps
from app.schemas.project import Project, ProjectCreate, ProjectUpdate, ProjectImage, ProjectModel3D
from app.services.project_service import ProjectService
from app.db.models.user import User

router = APIRouter()

@router.post("/", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user)
):
    return await service.create_project(project_in)

@router.get("/", response_model=List[Project])
async def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_active_user)
):
    return await service.get_projects(skip=skip, limit=limit)

@router.get("/public", response_model=List[Project])
async def list_public_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: ProjectService = Depends(deps.get_project_service)
):
    return await service.get_projects(skip=skip, limit=limit, only_public=True)

@router.get("/{id}", response_model=Project)
async def get_project(
    id: uuid.UUID,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_active_user)
):
    return await service.get_project(id)

@router.put("/{id}", response_model=Project)
async def update_project(
    id: uuid.UUID,
    project_in: ProjectUpdate,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user)
):
    return await service.update_project(id, project_in)

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    id: uuid.UUID,
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user)
):
    await service.delete_project(id)

@router.post("/{id}/images", response_model=List[ProjectImage])
async def upload_images(
    id: uuid.UUID,
    files: List[UploadFile] = File(...),
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user)
):
    return await service.add_project_images(id, files)

@router.post("/{id}/models", response_model=List[ProjectModel3D])
async def upload_models(
    id: uuid.UUID,
    files: List[UploadFile] = File(...),
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user)
):
    return await service.add_project_models(id, files)

@router.post("/{id}/shapefile", response_model=Project)
async def upload_shapefile(
    id: uuid.UUID,
    files: List[UploadFile] = File(...),
    service: ProjectService = Depends(deps.get_project_service),
    current_user: User = Depends(deps.get_current_admin_user)
):
    return await service.upload_shapefile(id, files)
