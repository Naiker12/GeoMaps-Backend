from typing import List, Optional
import uuid
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.db.models.project import (
    Project, ProjectImage, ProjectModel3D, 
    ProjectLocation, ProjectMetrics, ProjectFinancials, 
    ProjectMapSettings, ProjectAdminSettings
)
from geoalchemy2.functions import ST_GeomFromText

class ProjectRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_base_query(self):
        return select(Project).options(
            selectinload(Project.images),
            selectinload(Project.models_3d),
            selectinload(Project.location),
            selectinload(Project.metrics),
            selectinload(Project.financials),
            selectinload(Project.map_settings),
            selectinload(Project.admin_settings),
            selectinload(Project.lots)
        )

    async def get_all(self, skip: int = 0, limit: int = 100, only_public: bool = False) -> List[Project]:
        query = self._get_base_query()
        
        if only_public:
            # Ahora tenemos que unir con admin_settings para filtrar por is_publicly_visible
            query = query.join(Project.admin_settings).where(ProjectAdminSettings.is_publicly_visible == True)
        
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_by_id(self, project_id: uuid.UUID) -> Optional[Project]:
        query = self._get_base_query().where(Project.id == project_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create(self, project_data: dict) -> Project:
        # Extraer datos de tablas relacionadas
        location_data = project_data.pop("location", None)
        metrics_data = project_data.pop("metrics", None)
        financials_data = project_data.pop("financials", None)
        map_settings_data = project_data.pop("map_settings", None)
        admin_settings_data = project_data.pop("admin_settings", None)
        lots_data = project_data.pop("lots", [])

        # Crear el objeto proyecto base
        project = Project(**project_data)

        # Inicializar tablas relacionadas si hay datos
        if location_data:
            if "geometry_wkt" in location_data:
                wkt = location_data.pop("geometry_wkt")
                location_data["geometry"] = ST_GeomFromText(wkt, 4326)
            # Si no hay WKT pero hay coordenadas, generar un punto para PostGIS
            elif location_data.get("latitude") and location_data.get("longitude"):
                lat, lng = location_data["latitude"], location_data["longitude"]
                location_data["geometry"] = ST_GeomFromText(f"POINT({lng} {lat})", 4326)
            
            project.location = ProjectLocation(**location_data)
        else:
            project.location = ProjectLocation() # Crear vacío si se requiere por integridad

        if metrics_data:
            project.metrics = ProjectMetrics(**metrics_data)
        else:
            project.metrics = ProjectMetrics()

        if financials_data:
            project.financials = ProjectFinancials(**financials_data)
        else:
            project.financials = ProjectFinancials()

        if map_settings_data:
            project.map_settings = ProjectMapSettings(**map_settings_data)
        else:
            project.map_settings = ProjectMapSettings()

        if admin_settings_data:
            project.admin_settings = ProjectAdminSettings(**admin_settings_data)
        else:
            project.admin_settings = ProjectAdminSettings()

        from app.db.models.project import ProjectLot
        for lot_data in lots_data:
            if "geometry_wkt" in lot_data:
                wkt = lot_data.pop("geometry_wkt")
                lot_data["geometry"] = ST_GeomFromText(wkt, 4326)
            project.lots.append(ProjectLot(**lot_data))

        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        return await self.get_by_id(project.id)

    async def update(self, project_id: uuid.UUID, project_data: dict) -> Optional[Project]:
        # Obtener el proyecto con todas sus relaciones
        project = await self.get_by_id(project_id)
        if not project:
            return None

        # Extraer datos anidados
        location_data = project_data.pop("location", None)
        metrics_data = project_data.pop("metrics", None)
        financials_data = project_data.pop("financials", None)
        map_settings_data = project_data.pop("map_settings", None)
        admin_settings_data = project_data.pop("admin_settings", None)
        lots_data = project_data.pop("lots", None)

        # Actualizar campos del proyecto base
        for key, value in project_data.items():
            setattr(project, key, value)

        # Actualizar tablas relacionadas
        if location_data:
            if "geometry_wkt" in location_data:
                wkt = location_data.pop("geometry_wkt")
                location_data["geometry"] = ST_GeomFromText(wkt, 4326)
            # Si se están actualizando coordenadas sin WKT, actualizar también la geometría
            elif location_data.get("latitude") or location_data.get("longitude"):
                # Obtener valores finales (nuevos o existentes)
                curr_lat = location_data.get("latitude", project.location.latitude)
                curr_lng = location_data.get("longitude", project.location.longitude)
                if curr_lat and curr_lng:
                    location_data["geometry"] = ST_GeomFromText(f"POINT({curr_lng} {curr_lat})", 4326)

            for key, value in location_data.items():
                setattr(project.location, key, value)

        if metrics_data:
            for key, value in metrics_data.items():
                setattr(project.metrics, key, value)

        if financials_data:
            for key, value in financials_data.items():
                setattr(project.financials, key, value)

        if map_settings_data:
            for key, value in map_settings_data.items():
                setattr(project.map_settings, key, value)

        if admin_settings_data:
            for key, value in admin_settings_data.items():
                setattr(project.admin_settings, key, value)
        
        if lots_data is not None:
            # Reemplazo simple para evitar complejidad de merge por ahora
            project.lots = []
            from app.db.models.project import ProjectLot
            for lot_data in lots_data:
                if "geometry_wkt" in lot_data:
                    wkt = lot_data.pop("geometry_wkt")
                    lot_data["geometry"] = ST_GeomFromText(wkt, 4326)
                project.lots.append(ProjectLot(**lot_data))

        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def delete(self, project_id: uuid.UUID) -> bool:
        # El CASCADE borrará automáticamente las filas en las 5 tablas nuevas
        query = delete(Project).where(Project.id == project_id)
        result = await self.db.execute(query)
        await self.db.commit()
        return result.rowcount > 0

    async def add_image(self, project_id: uuid.UUID, image_url: str, order_index: int = 0) -> ProjectImage:
        image = ProjectImage(project_id=project_id, url=image_url, order_index=order_index)
        self.db.add(image)
        await self.db.commit()
        await self.db.refresh(image)
        return image

    async def add_model(self, project_id: uuid.UUID, model_url: str) -> ProjectModel3D:
        model = ProjectModel3D(project_id=project_id, url=model_url)
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return model

    async def get_image_count(self, project_id: uuid.UUID) -> int:
        query = select(ProjectImage).where(ProjectImage.project_id == project_id)
        result = await self.db.execute(query)
        return len(result.scalars().all())

    async def get_model_count(self, project_id: uuid.UUID) -> int:
        query = select(ProjectModel3D).where(ProjectModel3D.project_id == project_id)
        result = await self.db.execute(query)
        return len(result.scalars().all())
