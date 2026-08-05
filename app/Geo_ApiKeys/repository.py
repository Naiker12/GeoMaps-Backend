"""Repositorio de operaciones CRUD para API Keys.

Contiene: create, get_by_user, get_by_hash, list_admin_keys.
"""
import secrets
import hashlib
import uuid
from datetime import datetime
from typing import Optional, Sequence, Tuple

from sqlalchemy import select, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.Geo_ApiKeys.model import (
    APIKey, APIKeyStatus, APIKeyRole, APIKeyVisibility, APIKeyUsageLog,
)
from app.shared.base_repository import BaseRepository


class APIKeyCoreRepository(BaseRepository[APIKey]):
    """Operaciones CRUD sobre la tabla api_keys."""

    def __init__(self, db: AsyncSession):
        super().__init__(APIKey, db)

    async def create_key(
        self,
        user_id: uuid.UUID,
        name: str = "Primary Key",
        role: APIKeyRole = APIKeyRole.CLIENT,
        visibility: APIKeyVisibility = APIKeyVisibility.PRIVATE,
        description: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        rate_limit_rpm: Optional[int] = None,
    ) -> Tuple[APIKey, str]:
        """Genera una nueva API key, la hashea y guarda el hash."""
        raw_key = f"gm_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        db_obj = APIKey(
            user_id=user_id,
            name=name,
            key_prefix="gm_",
            key_hash=key_hash,
            hint=f"gm_...{raw_key[-4:]}",
            status=APIKeyStatus.ACTIVE,
            role=role,
            visibility=visibility,
            description=description,
            expires_at=expires_at,
            rate_limit_rpm=rate_limit_rpm,
        )
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj, raw_key

    async def get_by_user(
        self, user_id: uuid.UUID, active_only: bool = True
    ) -> Sequence[APIKey]:
        """Lista las keys de un usuario."""
        stmt = select(APIKey).where(APIKey.user_id == user_id)
        if active_only:
            stmt = stmt.where(APIKey.status == APIKeyStatus.ACTIVE)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_hash(self, key_hash: str) -> Optional[APIKey]:
        """Busca una key activa por hash, cargando la relación .user (eager)."""
        stmt = (
            select(APIKey)
            .where(APIKey.key_hash == key_hash, APIKey.status == APIKeyStatus.ACTIVE)
            .options(selectinload(APIKey.user))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_admin_keys(
        self,
        status: Optional[str] = None,
        role: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[Sequence[APIKey], int]:
        """Listado paginado para el panel de administración."""
        stmt = select(APIKey).options(joinedload(APIKey.user))

        if status:
            stmt = stmt.where(APIKey.status == status)
        if role:
            stmt = stmt.where(APIKey.role == role)
        if user_id:
            stmt = stmt.where(APIKey.user_id == user_id)
        if search:
            stmt = stmt.where(APIKey.name.ilike(f"%{search}%"))

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.db.execute(count_stmt)
        total_count = total.scalar_one()

        # Paginate
        stmt = (
            stmt.offset((page - 1) * limit)
            .limit(limit)
            .order_by(APIKey.created_at.desc())
        )
        result = await self.db.execute(stmt)
        keys_list = result.scalars().all()

        # Obtener distribución de tokens para cada key de la página actual
        if keys_list:
            key_ids = [k.id for k in keys_list]
            tokens_stmt = (
                select(
                    APIKeyUsageLog.api_key_id,
                    func.sum(case((APIKeyUsageLog.endpoint.like("%/layers%"), APIKeyUsageLog.tokens_used), else_=0)).label("layers"),
                    func.sum(case((APIKeyUsageLog.endpoint.like("%/projects%"), APIKeyUsageLog.tokens_used), else_=0)).label("projects"),
                    func.sum(case((or_(APIKeyUsageLog.endpoint.like("%/downloads%"), APIKeyUsageLog.endpoint.like("%/export%")), APIKeyUsageLog.tokens_used), else_=0)).label("downloads"),
                )
                .where(APIKeyUsageLog.api_key_id.in_(key_ids))
                .group_by(APIKeyUsageLog.api_key_id)
            )
            tokens_result = await self.db.execute(tokens_stmt)
            tokens_map = {row.api_key_id: {"layers": int(row.layers or 0), "projects": int(row.projects or 0), "downloads": int(row.downloads or 0)} for row in tokens_result}

            for k in keys_list:
                setattr(k, "token_distribution", tokens_map.get(k.id, {"layers": 0, "projects": 0, "downloads": 0}))

        return keys_list, total_count
