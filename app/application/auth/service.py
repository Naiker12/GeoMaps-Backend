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
from supabase import Client, create_client

from app.shared.core.config import settings
from app.core.security.jwt_handler import create_access_token
from app.core.security.password import verify_password
from app.core.utils.datetime import get_utc_now
from app.db.models.admin import Admin
from app.Geo_Usuarios.model import User
from app.Geo_Usuarios.model_session import UserSession
from app.schemas.auth_schema import AuthResponse
from app.schemas.user_schema import UserBase

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

        if not admin or not admin.is_active or not verify_password(password, admin.password_hash):
            return AuthResponse(success=False, message="Credenciales inválidas o cuenta inactiva")

        # Iniciar sesión admin
        expires = get_utc_now() + timedelta(hours=24)
        session = UserSession(
            user_id=admin.id,
            session_type="admin",
            ip_address=ip,
            user_agent=ua,
            expires_at=expires,
        )
        db.add(session)
        await db.flush()

        # Generar token con rol
        role = "SUPER_ADMIN" if admin.is_superadmin else "ADMIN"
        token = create_access_token({"sub": str(admin.id), "sid": str(session.id), "role": role})

        await db.commit()
        return AuthResponse(
            success=True,
            access_token=token,
            user=UserBase(
                id=admin.id,
                email=admin.email,
                full_name="Administrator",
                role=role,
                is_active=admin.is_active,
                created_at=admin.created_at,
            ),
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
            supabase_id = uuid.UUID(sub)
        except ValueError:
            logger.error(f"ID de Supabase no es un UUID válido: {sub}")
            raise HTTPException(status_code=400, detail=f"ID de Supabase inválido: {sub}")

        logger.info(f"Sincronizando sesión para: {email} ({sub})")

        # Buscar usuario local
        stmt = select(User).where(or_(User.email == email, User.supabase_id == supabase_id))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
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
        metadata = payload.get("user_metadata", {})
        provider = payload.get("app_metadata", {}).get("provider", "supabase")

        role_str = "ADMIN" if email == "admin@geomaps.com" or email.endswith("@geomaps.com") else "USER"
        name = metadata.get("name") or metadata.get("full_name") or email.split("@")[0]

        from app.Geo_Usuarios.model import UserRole
        role_enum = UserRole.ADMIN if role_str == "ADMIN" else UserRole.USER
        
        user = User(
            supabase_id=uuid.UUID(payload["sub"]),
            email=email,
            full_name=name,
            avatar_url=metadata.get("avatar_url") or metadata.get("picture"),
            auth_provider=provider,
            role=role_enum,
            is_active=True,
        )
        db.add(user)
        try:
            await db.flush()
            logger.info("👤 Perfil local creado: %s - Rol: %s", email, role_str)
            return user
        except Exception as exc:
            logger.critical("Error sincronizando perfil: %s", exc)
            raise HTTPException(status_code=500, detail="Fallo en sincronización local de perfil")

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
