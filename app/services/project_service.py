import uuid
import io
import zipfile
import time
import logging
from typing import List
from fastapi import UploadFile
from app.repositories.project_repository import ProjectRepository
from app.services.storage_service import storage_service
from app.services.geo_service import geo_service
from app.core.exceptions import ProjectNotFoundException, ValidationException
from app.db.models.project import InternalStatus, Project
from app.schemas.project import ProjectCreate, ProjectUpdate

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, repository: ProjectRepository):
        self.repository = repository

    async def get_projects(self, skip: int = 0, limit: int = 100, only_public: bool = False):
        return await self.repository.get_all(skip=skip, limit=limit, only_public=only_public)

    async def get_project(self, project_id: uuid.UUID) -> Project:
        project = await self.repository.get_by_id(project_id)
        if not project:
            raise ProjectNotFoundException(str(project_id))
        return project

    async def create_project(self, project_in: ProjectCreate) -> Project:
        return await self.repository.create(project_in.model_dump())

    async def update_project(self, project_id: uuid.UUID, project_in: ProjectUpdate) -> Project:
        project = await self.get_project(project_id)
        if project.internal_status == InternalStatus.ARCHIVADO:
            raise ValidationException("No se puede editar un proyecto archivado")
        return await self.repository.update(project_id, project_in.model_dump(exclude_unset=True))

    async def delete_project(self, project_id: uuid.UUID):
        await self.get_project(project_id)
        return await self.repository.delete(project_id)

    async def add_project_images(self, project_id: uuid.UUID, files: List[UploadFile]):
        import asyncio
        tasks = [self.add_project_image(project_id, file) for file in files]
        return await asyncio.gather(*tasks)

    async def add_project_models(self, project_id: uuid.UUID, files: List[UploadFile]):
        import asyncio
        tasks = [self.add_project_model(project_id, file) for file in files]
        return await asyncio.gather(*tasks)

    async def add_project_image(self, project_id: uuid.UUID, file: UploadFile):
        project = await self.get_project(project_id)
        if project.internal_status == InternalStatus.ARCHIVADO:
            raise ValidationException("No se puede modificar un proyecto archivado")
        count = await self.repository.get_image_count(project_id)
        if count >= 10:
            raise ValidationException("El proyecto ya tiene el máximo permitido de 10 imágenes")
        url = await storage_service.upload_file(file, "images")
        return await self.repository.add_image(project_id, url, order_index=count)

    async def add_project_model(self, project_id: uuid.UUID, file: UploadFile):
        project = await self.get_project(project_id)
        if project.internal_status == InternalStatus.ARCHIVADO:
            raise ValidationException("No se puede modificar un proyecto archivado")
        count = await self.repository.get_model_count(project_id)
        if count >= 4:
            raise ValidationException("El proyecto ya tiene el máximo permitido de 4 modelos 3D")
        url = await storage_service.upload_file(file, "models")
        return await self.repository.add_model(project_id, url)

    async def upload_shapefile(self, project_id: uuid.UUID, files: list[UploadFile]):
        start_total = time.time()
        project = await self.get_project(project_id)

        if project.internal_status == InternalStatus.ARCHIVADO:
            raise ValidationException("No se puede modificar un proyecto archivado")
        if not files:
            raise ValidationException("No se proporcionaron archivos de cartografía")

        try:
            # 1. Empaquetar archivos si no vienen en un ZIP
            if len(files) == 1 and files[0].filename.lower().endswith('.zip'):
                await files[0].seek(0)
                final_content = await files[0].read()
                final_filename = files[0].filename
            else:
                final_filename = f"shapefile_{project_id.hex[:8]}.zip"
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for file in files:
                        await file.seek(0)
                        zf.writestr(file.filename, await file.read())
                final_content = zip_buffer.getvalue()

            # 2. Subir el ZIP a storage (como respaldo y para descarga)
            from fastapi import UploadFile as FastAPIUploadFile
            mock_file = FastAPIUploadFile(file=io.BytesIO(final_content), filename=final_filename)
            zip_url = await storage_service.upload_file(mock_file, "shapefiles")

            # 3. Procesar datos geoespaciales
            file_data = []
            for file in files:
                await file.seek(0)
                file_data.append((file.filename, await file.read()))

            logger.info(f"Procesando cartografía para el proyecto {project_id}...")
            geodata = await geo_service.process_shapefile(file_data)
            
            # 4. Actualizar base de datos con los resultados del procesamiento
            update_data = {
                "location": {
                    "shapefile_url": zip_url,
                    "geometry_wkt": geodata["geometry_wkt"]
                },
                "metrics": {
                    "total_area": float(geodata["total_area"]),
                    "lots": len(geodata.get("lots", []))
                },
                "lots": geodata.get("lots", [])
            }

            # Solo sobreescribir coordenadas si son válidas (distintas al fallback 0,0)
            c_lat = geodata.get("centroid_lat")
            c_lon = geodata.get("centroid_lon")

            if c_lat != 0.0 or c_lon != 0.0:
                logger.info(f"Actualizando coordenadas del proyecto {project_id} con centroide del shapefile: ({c_lat}, {c_lon})")
                update_data["location"]["latitude"] = c_lat
                update_data["location"]["longitude"] = c_lon
            else:
                logger.info(f"Omitiendo actualización de coordenadas para {project_id} (centroide 0,0 - Falta CRS o geometría vacía)")

            # Si el procesamiento fue parcial (falta CRS), podemos registrarlo
            if geodata.get("status") == "CRS_MISSING":
                logger.warning(f"Proyecto {project_id} actualizado con cartografía sin CRS (.prj missing)")
                # Aquí podrías añadir un flag en la DB si existiera la columna 'cartography_status'
        
            result = await self.repository.update(project_id, update_data)
            logger.info(f"Shapefile procesado ({geodata['status']}) exitosamente en {time.time() - start_total:.2f}s para proyecto {project_id}")
            return result

        except Exception as e:
            logger.error(f"Error procesando archivos para proyecto {project_id}: {str(e)}")
            if isinstance(e, ValidationException):
                raise
            raise ValidationException(f"Error al procesar la cartografía: {str(e)}")
