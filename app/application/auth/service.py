"""Servicio de autenticación asíncrono.
Sincroniza usuarios locales con Supabase y gestiona sesiones de administración.
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from supabase import Client, create_client

from app.core.config import settings
from app.core.security.jwt_handler import create_access_token
from app.core.security.password import verify_password
from app.core.utils.datetime import get_utc_now
from app.db.models.admin import Admin
from app.db.models.user import User, UserRole
from app.db.models.user_session import UserSession
from app.schemas.auth_schema import AuthResponse

logger = logging.getLogger(__name__)


class AuthService:
    """Orquestador de procesos de identidad y sesiones."""

    def __init__(self) -> None:
        self.supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)

    async def login_admin(
        self,
        email: str,
        password: str,
        db: AsyncSession,
        ip: str | None = None,
        ua: str | None = None,
    ) -> AuthResponse:
        """Autenticación para administradores de GeoMaps."""
        stmt = select(Admin).where(Admin.email == email)
        result = await db.execute(stmt)
        admin = result.scalar_one_or_none()

        if not admin or not admin.is_active:
            return AuthResponse(success=False, message="Credenciales inválidas o cuenta inactiva")
        if not await run_in_threadpool(verify_password, password, admin.password_hash):
            return AuthResponse(success=False, message="Credenciales inválidas o cuenta inactiva")

        result = await db.execute(select(User).where(User.email == admin.email))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active or user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            return AuthResponse(success=False, message="No existe un perfil administrativo activo")

        # Iniciar sesión admin
        expires = get_utc_now() + timedelta(hours=24)
        session = UserSession(
            user_id=user.id,
            session_type="admin",
            ip_address=ip,
            user_agent=ua,
            expires_at=expires,
        )
        db.add(session)
        await db.flush()

        # Generar token con rol
        token = create_access_token({"sub": str(user.id), "sid": str(session.id), "role": user.role})

        await db.commit()
        return AuthResponse(
            success=True,
            access_token=token,
            user={
                "id": str(user.id), "email": user.email, "full_name": user.full_name,
                "role": user.role, "avatar_url": user.avatar_url,
            },
        )

    async def start_user_session(
        self,
        payload: dict,
        db: AsyncSession,
        ip: str | None = None,
        ua: str | None = None,
    ) -> tuple[User, str]:
        """Sincroniza un usuario autenticado por Supabase y le otorga sesión backend."""
        sub = payload.get("sub")
        email = payload.get("email")

        if not sub:
            raise HTTPException(status_code=401, detail="Token Supabase inválido: falta 'sub'")

        try:
            supabase_id = uuid.UUID(str(sub))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(status_code=401, detail="Identidad Supabase inválida") from exc

        if not isinstance(email, str) or not email.strip():
            raise HTTPException(status_code=401, detail="El token Supabase no contiene un correo válido")

        logger.info(f"Sincronizando sesión para: {email} ({sub})")

        # Buscar usuario local
        stmt = select(User).where(or_(User.email == email, User.supabase_id == supabase_id))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            if not user.is_active:
                raise HTTPException(status_code=403, detail="Cuenta de usuario desactivada")
            logger.info(f"Usuario {email} encontrado localmente. Actualizando ID.")
            user.supabase_id = supabase_id
            user.email = email or user.email
        else:
            logger.info(f"Usuario {email} no existe localmente. Creando nuevo perfil.")
            user = await self._create_local_user(payload, db)

        if not user.is_active:
            logger.warning(f"Intento de login para usuario inactivo: {email}")
            raise HTTPException(status_code=403, detail="Cuenta de usuario desactivada")

        # Crear sesión
        expires = get_utc_now() + timedelta(hours=24)
        session = UserSession(
            user_id=user.id,
            session_type="user",
            ip_address=ip,
            user_agent=ua,
            expires_at=expires,
        )
        db.add(session)
        await db.flush()

        token = create_access_token({"sub": str(user.id), "sid": str(session.id)})

        user.last_login = get_utc_now()
        await db.commit()
        return user, token

    async def _create_local_user(self, payload: dict, db: AsyncSession) -> User:
        """Helper privado para crear perfiles locales desde Supabase."""
        email = payload.get("email", "")
        metadata = payload.get("user_metadata") or {}
        app_metadata = payload.get("app_metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        if not isinstance(app_metadata, dict):
            app_metadata = {}
        provider = app_metadata.get("provider", "supabase")
        name = metadata.get("name") or metadata.get("full_name") or email.split("@")[0]

        user = User(
            supabase_id=uuid.UUID(payload["sub"]),
            email=email,
            full_name=name,
            avatar_url=metadata.get("avatar_url") or metadata.get("picture"),
            auth_provider=provider,
            # Los privilegios se asignan explícitamente desde administración.
            role=UserRole.USER,
            is_active=True,
        )
        db.add(user)
        try:
            await db.flush()
            logger.info("Perfil local creado: %s", email)
            return user
        except SQLAlchemyError as exc:
            await db.rollback()
            logger.critical("Error sincronizando perfil: %s", exc)
            raise HTTPException(status_code=500, detail="Fallo en sincronización local de perfil") from exc

    async def update_user_profile(self, db: AsyncSession, user: User, update_data: Any) -> User:
        """Actualiza campos editables del perfil desde UserUpdate schema."""
        fields = ["full_name", "avatar_url", "job_title", "bio", "phone"]
        for field in fields:
            val = getattr(update_data, field, None)
            if val is not None:
                setattr(user, field, val)

        await db.commit()
        await db.refresh(user)
        return user

    async def get_active_sessions(self, user_id: uuid.UUID, db: AsyncSession) -> list[UserSession]:
        stmt = (
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.logout_at.is_(None),
                UserSession.expires_at > get_utc_now(),
            )
            .order_by(UserSession.login_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def revoke_session(self, sid: uuid.UUID, uid: uuid.UUID, db: AsyncSession) -> bool:
        stmt = select(UserSession).where(UserSession.id == sid, UserSession.user_id == uid)
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if session:
            session.logout_at = get_utc_now()
            await db.commit()
            return True
        return False


auth_service = AuthService()
