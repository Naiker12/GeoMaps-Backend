"""Repositorio de Proyectos de Desarrollo Urbano.
Gestiona la entidad Project y sus tablas relacionadas.
"""

import uuid
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from geoalchemy2.functions import ST_GeomFromText

from app.db.models.project import (
    Project, ProjectAdminSettings, ProjectFinancials, 
    ProjectImage, ProjectLocation, ProjectLot, 
    ProjectMapSettings, ProjectMetrics, ProjectModel3D
)
from app.repositories.base_repository import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """Orquestador de datos complejos para proyectos cartográficos."""

    def __init__(self, db: AsyncSession):
        super().__init__(Project, db)

    def _get_base_query(self):
        """Query base con Eager Loading de todas las relaciones."""
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

    async def get_all_projects(self, skip: int = 0, limit: int = 100, only_public: bool = False) -> Sequence[Project]:
        """Obtiene la lista de proyectos con filtrado de visibilidad."""
        stmt = self._get_base_query()
        if only_public:
            stmt = stmt.join(Project.admin_settings).where(ProjectAdminSettings.is_publicly_visible == True)
        
        stmt = stmt.offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_project_by_id(self, project_id: uuid.UUID) -> Project | None:
        """Busca un proyecto detallado por su identificador único."""
        stmt = self._get_base_query().where(Project.id == project_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_project(self, project_data: dict) -> Project:
        """Crea un proyecto y sus entidades relacionadas en una transacción."""
        child_models = {
            "location": ProjectLocation,
            "metrics": ProjectMetrics,
            "financials": ProjectFinancials,
            "map_settings": ProjectMapSettings,
            "admin_settings": ProjectAdminSettings
        }

        lots_data = project_data.pop("lots", [])
        project_lots = [ProjectLot(**self._process_geom(l)) for l in lots_data]
        
        related_instances = {}
        for key, model_cls in child_models.items():
            data = project_data.pop(key, {})
            if data is None: data = {} # Asegurar dict si viene None de Pydantic
            if key == "location": 
                data = self._process_geom(data)
            related_instances[key] = model_cls(**data)

        project = Project(**project_data, **related_instances, lots=project_lots)
        
        self.db.add(project)
        await self.db.commit()
        return await self.get_project_by_id(project.id)

    async def update_project(self, project_id: uuid.UUID, project_data: dict) -> Project | None:
        """Actualización profunda de proyecto y sus tablas vinculadas."""
        project = await self.get_project_by_id(project_id)
        if not project: return None

        single_rels = ["location", "metrics", "financials", "map_settings", "admin_settings"]
        for rel in single_rels:
            data = project_data.pop(rel, None)
            if data is not None and isinstance(data, dict):
                if rel == "location": data = self._process_geom(data, project.location)
                target = getattr(project, rel)
                for k, v in data.items(): setattr(target, k, v)

        lots_data = project_data.pop("lots", None)
        if lots_data is not None:
            project.lots = [ProjectLot(**self._process_geom(l)) for l in lots_data]

        for key, value in project_data.items():
            setattr(project, key, value)

        await self.db.commit()
        await self.db.refresh(project)
        return project

    def _process_geom(self, data: dict, existing_loc: Any = None) -> dict:
        """Convierte datos crudos a formatos geométricos PostGIS."""
        if "geometry_wkt" in data:
            data["geometry"] = ST_GeomFromText(data.pop("geometry_wkt"), 4326)
        elif data.get("latitude") and data.get("longitude"):
            lat = data.get("latitude") or (existing_loc.latitude if existing_loc else 0)
            lng = data.get("longitude") or (existing_loc.longitude if existing_loc else 0)
            data["geometry"] = ST_GeomFromText(f"POINT({lng} {lat})", 4326)
        return data

    async def get_lots_as_geojson(self, project_id: uuid.UUID) -> dict:
        """Construye una FeatureCollection GeoJSON con los lotes de un proyecto.

        Usa ST_AsGeoJSON() de PostGIS para conversión eficiente en la DB.
        Incluye metadata visual (color, opacidad) y financiera (moneda).
        """
        import json
        from sqlalchemy import func

        # Obtener proyecto con relaciones necesarias
        project = await self.get_project_by_id(project_id)
        if not project:
            return {"type": "FeatureCollection", "features": [], "metadata": {}}

        currency = project.financials.currency.value if project.financials else "COP"
        map_color = project.map_settings.map_color if project.map_settings else "#3ECF8E"
        map_opacity = project.map_settings.map_opacity if project.map_settings else 100

        # Query eficiente: solo campos necesarios + geometría PostGIS → GeoJSON
        stmt = select(
            ProjectLot.id,
            ProjectLot.identifier,
            ProjectLot.nz_zone,
            ProjectLot.area_m2,
            ProjectLot.status,
            ProjectLot.price,
            ProjectLot.custom_data,
            func.ST_AsGeoJSON(ProjectLot.geometry).label("geometry")
        ).where(ProjectLot.project_id == project_id)

        result = await self.db.execute(stmt)
        rows = result.mappings().all()

        features = []
        for row in rows:
            geom = json.loads(row["geometry"]) if row["geometry"] else None
            features.append({
                "type": "Feature",
                "id": str(row["id"]),
                "geometry": geom,
                "properties": {
                    "lot_id": str(row["id"]),
                    "name": row["identifier"],
                    "nz_zone": row["nz_zone"],
                    "area": float(row["area_m2"]) if row["area_m2"] else None,
                    "status": row["status"] or "Disponible",
                    "price": float(row["price"]) if row["price"] else None,
                    "currency": currency,
                    "project_id": str(project_id),
                    "custom_data": row["custom_data"]
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "project_name": project.name,
                "map_color": map_color,
                "map_opacity": map_opacity,
                "total_lots": len(features)
            }
        }

    async def manage_media(self, project_id: uuid.UUID, url: str, media_type: str = "image") -> Any:
        """Gestor de archivos multimedia (imágenes o modelos 3D)."""
        model = ProjectImage if media_type == "image" else ProjectModel3D
        instance = model(project_id=project_id, url=url)
        self.db.add(instance)
        await self.db.commit()
        return instance

    async def update_lot(self, lot_id: uuid.UUID, lot_data: dict) -> ProjectLot | None:
        """Actualiza un lote específico."""
        stmt = select(ProjectLot).where(ProjectLot.id == lot_id)
        result = await self.db.execute(stmt)
        lot = result.scalar_one_or_none()
        
        if not lot:
            return None
            
        for k, v in lot_data.items():
            if v is not None:
                setattr(lot, k, v)
                
        await self.db.commit()
        await self.db.refresh(lot)
        return lot
