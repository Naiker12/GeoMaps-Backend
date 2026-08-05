"""Servicio integral para gestión de proyectos inmobiliarios y cartográficos.
Orquestador de carga de archivos (imágenes, modelos 3D, planos) y metadatos.
"""

import logging
import uuid
from typing import Any, Sequence
from fastapi import UploadFile
from app.Geo_Proyectos.repository import ProjectRepository
from app.Geo_Proyectos.schemas import ProjectCreate, ProjectUpdate
from app.Geo_Proyectos.model import Project

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MODEL_EXTENSIONS = {".glb", ".gltf", ".obj", ".fbx"}
SHAPE_EXTENSIONS = {".zip", ".geojson", ".json", ".shp"}
LOT_STATUS_ALIASES = {
    "disponible": "Disponible",
    "reservado": "Reservado",
    "vendido": "Vendido",
    "proceso": "En Proceso",
    "en proceso": "En Proceso",
    "en_proceso": "En Proceso",
}


def normalize_lot_status(status: Any) -> str:
    value = str(status or "Disponible").strip()
    return LOT_STATUS_ALIASES.get(value.lower(), value)


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

    async def update_lot(self, lot_id: uuid.UUID, lot_in: Any) -> Any:
        """Actualiza la información (precio, estado, etc.) de un lote."""
        lot_data = lot_in.model_dump(exclude_unset=True)
        if "status" in lot_data:
            lot_data["status"] = normalize_lot_status(lot_data["status"])
        return await self.repository.update_lot(lot_id, lot_data)

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

    async def get_lots_geojson(self, project_id: uuid.UUID) -> dict:
        """Obtiene los lotes del proyecto como FeatureCollection GeoJSON."""
        return await self.repository.get_lots_as_geojson(project_id)

    async def _classify_and_upload(self, project_id: uuid.UUID, file: UploadFile):
        """Helper privado para clasificar y subir archivos según su extensión."""
        from app.Geo_Storage.service import storage_service
        
        filename = file.filename.lower() if file.filename else ""
        if any(filename.endswith(ext) for ext in IMAGE_EXTENSIONS):
            url = await storage_service.upload_file(file, "projects/images")
            await self.repository.manage_media(project_id, url, "image")
            
        elif any(filename.endswith(ext) for ext in MODEL_EXTENSIONS):
            url = await storage_service.upload_file(file, "projects/models")
            await self.repository.manage_media(project_id, url, "model")
            
        elif any(filename.endswith(ext) for ext in SHAPE_EXTENSIONS):
            logger.info(f"Shapefile detectado en proyecto {project_id}")
            await self._process_project_shapefile(project_id, file)

    async def _process_project_shapefile(self, project_id: uuid.UUID, file: UploadFile):
        """Procesa un shapefile/GeoJSON y lo inserta en project_lots como polígonos PostGIS."""
        import json
        import tempfile
        import geopandas as gpd
        from app.Geo_Storage.service import storage_service
        from geoalchemy2.functions import ST_GeomFromText
        from app.Geo_Proyectos.model import ProjectLot

        # 1. Subir a Storage
        file.file.seek(0)
        url = await storage_service.upload_file(file, "Shapefile")

        # 2. Guardar URL en project_locations
        await self.repository.update_project(project_id, {
            "location": {"shapefile_url": url}
        })

        # 3. Leer contenido del archivo
        file.file.seek(0)
        content = await file.read()
        filename = file.filename.lower() if file.filename else ""

        try:
            if filename.endswith(".zip"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
                gdf = gpd.read_file(f"zip://{tmp_path}")
            elif filename.endswith((".geojson", ".json")):
                text = content.decode("utf-8", errors="replace")
                geojson_data = json.loads(text)
                gdf = gpd.GeoDataFrame.from_features(geojson_data.get("features", []))
            else:
                logger.warning(f"Formato no soportado para project lots: {filename}")
                return

            # 4. Reproyectar a EPSG:4326 si es necesario
            if gdf.crs and str(gdf.crs) != "EPSG:4326":
                gdf = gdf.to_crs(epsg=4326)
            elif not gdf.crs:
                gdf = gdf.set_crs(epsg=4326)

            # 5. Calcular áreas en m² (proyección métrica temporal)
            gdf_metric = gdf.to_crs(epsg=3857)
            gdf["area_m2"] = gdf_metric.geometry.area

            # 6. Detectar campo de nombre/identificador
            name_candidates = ['nombre', 'name', 'lote', 'lot', 'identifier', 'id', 'manzana', 'label']
            name_field = None
            for col in gdf.columns:
                if col.lower() in name_candidates:
                    name_field = col
                    break

            # 7. Reemplazar lotes existentes e insertar nuevas features.
            lots_replaced = await self.repository.delete_project_lots(project_id)
            lots_created = 0
            all_geoms = []
            
            for idx, row in gdf.iterrows():
                if row.geometry is None or row.geometry.is_empty:
                    continue

                all_geoms.append(row.geometry)
                identifier = str(row[name_field]) if name_field and name_field in row else f"Lote {idx + 1}"

                # Extraer custom_data
                props = {}
                for col in gdf.columns:
                    if col not in ('geometry', 'area_m2') and row[col] is not None:
                        val = row[col]
                        if hasattr(val, 'item'):
                            val = val.item()
                        props[col] = val

                lot = ProjectLot(
                    project_id=project_id,
                    identifier=identifier,
                    area_m2=round(float(row["area_m2"]), 2),
                    status="Disponible",
                    geometry=ST_GeomFromText(row.geometry.wkt, 4326),
                    custom_data=props if props else None,
                )
                self.repository.db.add(lot)
                lots_created += 1

            # 8. Actualizar geometría del proyecto (Límite Global)
            if all_geoms:
                from shapely.ops import unary_union
                project_union = unary_union(all_geoms)
                
                # Si el proyecto ya tiene ubicación, actualizamos solo el campo geometry
                await self.repository.update_project(project_id, {
                    "location": {
                        "geometry": project_union.wkt,
                        # Conservar coordenadas del centroide para el marcador si no existen
                        "latitude": project_union.centroid.y,
                        "longitude": project_union.centroid.x
                    }
                })

            await self.repository.db.commit()
            logger.info(
                "Proyecto %s: %s lotes reemplazados, %s lotes insertados",
                project_id,
                lots_replaced,
                lots_created,
            )

        except Exception as e:
            logger.exception(f"Error procesando shapefile para proyecto {project_id}: {e}")
            await self.repository.db.rollback()
            raise RuntimeError(f"No se pudo procesar el archivo cartografico: {e}") from e
