"""Servicio integral para gestión de proyectos inmobiliarios y cartográficos.
Orquestador de carga de archivos (imágenes, modelos 3D, planos) y metadatos.
"""

import logging
import uuid
from typing import Any, Sequence
from fastapi import UploadFile
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.db.models.project import Project

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MODEL_EXTENSIONS = {".glb", ".gltf", ".obj", ".fbx"}
SHAPE_EXTENSIONS = {".zip", ".geojson", ".json", ".shp"}


class ProjectService:
    """Implementa lógica de negocio para Proyectos Urbanos."""

    def __init__(self, db: Any):
        self.repository = ProjectRepository(db)

    async def get_projects(self, only_public: bool = False, skip: int = 0, limit: int = 100) -> Sequence[Project]:
        """Obtiene una lista paginada de proyectos filtrados por visibilidad."""
        return await self.repository.get_all_projects(skip=skip, limit=limit, only_public=only_public)

    async def get_project_by_id(self, project_id: uuid.UUID) -> Project | None:
        """Obtiene el detalle completo de un proyecto y sus entidades vinculadas."""
        return await self.repository.get_project_by_id(project_id)

    async def create_project(self, project_in: ProjectCreate, files: list[UploadFile] = []) -> Project:
        """Inicializa un proyecto y clasifica archivos multimedia automáticamente."""
        project_data = project_in.model_dump()
        project = await self.repository.create_project(project_data)

        if files:
            for file in files:
                await self._classify_and_upload(project.id, file)

        return project

    async def update_project(self, project_id: uuid.UUID, project_in: ProjectUpdate) -> Project | None:
        """Actualiza la información profunda del proyecto (Deep Update)."""
        project_data = project_in.model_dump(exclude_unset=True)
        return await self.repository.update_project(project_id, project_data)

    async def delete_project(self, project_id: uuid.UUID) -> bool:
        """Elimina permanentemente un proyecto y todas sus relaciones."""
        return await self.repository.delete(project_id)

    async def add_project_images(self, project_id: uuid.UUID, files: list[UploadFile]) -> list[Any]:
        """Sube múltiples imágenes y las vincula al proyecto."""
        for file in files:
            await self._classify_and_upload(project_id, file)
        project = await self.get_project_by_id(project_id)
        return project.images if project else []

    async def add_project_models(self, project_id: uuid.UUID, files: list[UploadFile]) -> list[Any]:
        """Sube múltiples modelos 3D y los vincula al proyecto."""
        for file in files:
            await self._classify_and_upload(project_id, file)
        project = await self.get_project_by_id(project_id)
        return project.models_3d if project else []

    async def upload_shapefile(self, project_id: uuid.UUID, files: list[UploadFile]) -> Project | None:
        """Sube y procesa shapefiles (capas vectoriales) para el proyecto."""
        for file in files:
            await self._classify_and_upload(project_id, file)
        return await self.get_project_by_id(project_id)

    async def _classify_and_upload(self, project_id: uuid.UUID, file: UploadFile):
        """Helper privado para clasificar y subir archivos según su extensión."""
        from app.services.storage_service import storage_service
        
        filename = file.filename.lower() if file.filename else ""
        if any(filename.endswith(ext) for ext in IMAGE_EXTENSIONS):
            url = await storage_service.upload_file(file, "projects/images")
            await self.repository.manage_media(project_id, url, "image")
            
        elif any(filename.endswith(ext) for ext in MODEL_EXTENSIONS):
            url = await storage_service.upload_file(file, "projects/models")
            await self.repository.manage_media(project_id, url, "model")
            
        elif any(filename.endswith(ext) for ext in SHAPE_EXTENSIONS):
            from app.services.layer_service import LayerService
            logger.info(f"Shapefile detectado en proyecto {project_id}")
            # Procesamiento geoespacial embebido si fuera requerido
