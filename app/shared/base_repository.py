"""Clase base genérica para repositorios con SQLAlchemy Async.
Implementa operaciones CRUD estándar para reducir el código duplicado.
"""

import uuid
from typing import Any, Generic, Sequence, Type, TypeVar

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

# Tipo genérico para modelos SQLAlchemy
ModelType = TypeVar("ModelType", bound=DeclarativeBase)


class BaseRepository(Generic[ModelType]):
    """Gestor de acceso a datos genérico con soporte asíncrono."""

    def __init__(self, model: Type[ModelType], db: AsyncSession):
        self.model = model
        self.db = db

    async def get(self, id: uuid.UUID | int) -> ModelType | None:
        """Obtiene un registro por su ID único."""
        stmt = select(self.model).where(self.model.id == id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self, 
        skip: int = 0, 
        limit: int = 100, 
        **filters
    ) -> Sequence[ModelType]:
        """Obtiene múltiples registros con paginación y filtros dinámicos."""
        stmt = select(self.model).offset(skip).limit(limit)
        
        # Aplicación de filtros automáticos (si el campo existe en el modelo)
        for field, value in filters.items():
            if value is not None and hasattr(self.model, field):
                stmt = stmt.where(getattr(self.model, field) == value)
                
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create(self, obj_in_data: dict[str, Any]) -> ModelType:
        """Persiste un nuevo objeto en la base de datos."""
        db_obj = self.model(**obj_in_data)
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def update(
        self, 
        db_obj: ModelType, 
        obj_in_data: dict[str, Any]
    ) -> ModelType:
        """Actualiza campos específicos de un objeto persistido."""
        for field in obj_in_data:
            if hasattr(db_obj, field):
                setattr(db_obj, field, obj_in_data[field])
        
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def delete(self, id: uuid.UUID | int) -> bool:
        """Elimina un registro y retorna True si se borró con éxito."""
        stmt = delete(self.model).where(self.model.id == id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0
