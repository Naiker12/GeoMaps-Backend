import uuid
import logging
from datetime import timedelta
from typing import Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_
from fastapi import HTTPException, status
from app.db.models.user import User, UserRole
from app.db.models.admin import Admin
from app.db.models.user_session import UserSession
from app.schemas.auth_schema import AuthResponse
from app.schemas.user_schema import UserBase, UserUpdate
from app.core.config import settings
from app.core.security.password import verify_password
from app.core.security.jwt_handler import create_access_token
from app.core.utils.datetime import get_utc_now
from supabase import create_client, Client

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self):
        self.supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)

    async def send_magic_link(self, email: str) -> AuthResponse:
        try:
            self.supabase.auth.sign_in_with_otp({
                "email": email,
                "options": {
                    "should_create_user": True,
                    "email_redirect_to": f"{settings.FRONTEND_URL}/Midas-Frontend/auth/callback"
                }
            })
            return AuthResponse(success=True, message="Enlace de activación enviado. Revisa tu correo.")
        except Exception as e:
            return AuthResponse(success=False, message=str(e))

    async def login_admin(self, email: str, password: str, db: Session, ip_address: str = None, user_agent: str = None) -> AuthResponse:
        try:
            admin = db.query(Admin).filter(Admin.email == email).first()
            if not admin or not admin.is_active:
                return AuthResponse(success=False, message="Credenciales inválidas o cuenta desactivada")

            if not verify_password(password, admin.password_hash):
                return AuthResponse(success=False, message="Credenciales inválidas")

            expires_at = get_utc_now() + timedelta(hours=24)
            session = UserSession(
                user_id=admin.id,
                session_type="admin",
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=expires_at
            )
            db.add(session)
            db.flush()

            access_token = create_access_token({
                "sub": str(admin.id),
                "sid": str(session.id),
                "type": "admin_session",
                "role": "SUPER_ADMIN" if admin.is_superadmin else "ADMIN"
            })

            db.commit()
            return AuthResponse(
                success=True,
                access_token=access_token,
                user=UserBase(
                    id=admin.id,
                    email=admin.email,
                    full_name="Administrator",
                    role="SUPER_ADMIN" if admin.is_superadmin else "ADMIN",
                    is_active=admin.is_active,
                    created_at=admin.created_at
                )
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Error en login admin: {str(e)}")
            return AuthResponse(success=False, message="Error interno en el servidor")

    async def start_user_session(
        self,
        payload: dict,
        db: AsyncSession,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> tuple[User, str]:
        supabase_id_str = payload.get("sub")
        email = payload.get("email")
        user_metadata = payload.get("user_metadata", {})

        if not supabase_id_str:
            raise HTTPException(status_code=401, detail="Token de Supabase inválido: falta 'sub'")

        supabase_uuid = uuid.UUID(supabase_id_str)

        from sqlalchemy import select
        result = await db.execute(select(User).filter(
            or_(User.email == email, User.supabase_id == supabase_uuid)
        ))
        user = result.scalar_one_or_none()

        if user:
            if user.supabase_id != supabase_uuid:
                user.supabase_id = supabase_uuid
            if email and user.email != email:
                user.email = email
        else:
            try:
                email_str = email or ""
                initial_role = "ADMIN" if email_str == "admin@geomaps.com" or email_str.endswith("@geomaps.com") else "USER"
                
                name_from_email = email_str.split("@")[0] if "@" in email_str else "User"
                
                user = User(
                    supabase_id=supabase_uuid,
                    email=email,
                    full_name=user_metadata.get("full_name") or user_metadata.get("name") or name_from_email,
                    avatar_url=user_metadata.get("avatar_url") or user_metadata.get("picture"),
                    auth_provider="google" if payload.get("app_metadata", {}).get("provider") == "google" else "supabase",
                    role=initial_role,
                    is_active=True
                )
                db.add(user)
                await db.flush()
                logger.info(f"Usuario {email} creado con rol {initial_role}")
            except Exception as e:
                await db.rollback()
                logger.error(f"Error creando usuario local: {str(e)}")
                raise HTTPException(status_code=500, detail="Error al sincronizar perfil de usuario")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Cuenta desactivada")

        expires_at = get_utc_now() + timedelta(hours=24)
        session = UserSession(
            user_id=user.id,
            session_type="user",
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at
        )
        db.add(session)
        await db.flush()

        access_token = create_access_token({
            "sub": str(user.id),
            "sid": str(session.id),
            "type": "user_session"
        })

        user.last_login = get_utc_now()
        await db.commit()

        return user, access_token

    def invalidate_session(self, session_id: str, db: Session):
        try:
            session = db.query(UserSession).filter(UserSession.id == session_id).first()
            if session:
                session.logout_at = get_utc_now()
                db.commit()
        except Exception as e:
            logger.error(f"Error al invalidar sesión: {str(e)}")
            db.rollback()


    async def update_user_profile(self, db: AsyncSession, user: User, update_data: Any) -> User:
        try:
            if update_data.full_name is not None:
                user.full_name = update_data.full_name
            if update_data.avatar_url is not None:
                user.avatar_url = update_data.avatar_url
            if update_data.job_title is not None:
                user.job_title = update_data.job_title
            if update_data.bio is not None:
                user.bio = update_data.bio
            if update_data.phone is not None:
                user.phone = update_data.phone
            
            await db.commit()
            await db.refresh(user)
            return user
        except Exception as e:
            await db.rollback()
            logger.error(f"Error al actualizar perfil: {str(e)}")
            raise HTTPException(status_code=500, detail="Error interno al actualizar el perfil")

    async def get_active_sessions(self, user_id: uuid.UUID, db: AsyncSession) -> list[UserSession]:
        from sqlalchemy import select
        result = await db.execute(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.logout_at == None,
                UserSession.expires_at > get_utc_now()
            ).order_by(UserSession.login_at.desc())
        )
        return list(result.scalars().all())

    async def revoke_session(self, session_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> bool:
        from sqlalchemy import select
        result = await db.execute(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.user_id == user_id
            )
        )
        session = result.scalar_one_or_none()
        if session:
            session.logout_at = get_utc_now()
            await db.commit()
            return True
        return False

auth_service = AuthService()
