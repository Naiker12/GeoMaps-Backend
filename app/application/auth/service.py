import uuid
import logging
from datetime import timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_
from fastapi import HTTPException, status
from app.domain.models.user import User
from app.domain.models.admin import Admin
from app.domain.models.user_session import UserSession
from app.schemas.auth_schema import AuthResponse, UserBase
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

            access_token = create_access_token(data={
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
                    id=str(admin.id),
                    email=admin.email,
                    full_name="Administrator",
                    role="SUPER_ADMIN" if admin.is_superadmin else "ADMIN"
                )
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Error en login admin: {str(e)}")
            return AuthResponse(success=False, message="Error interno en el servidor")

    def start_user_session(
        self,
        payload: dict,
        db: Session,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> tuple[User, str]:
        supabase_id_str = payload.get("sub")
        email = payload.get("email")
        user_metadata = payload.get("user_metadata", {})

        if not supabase_id_str:
            raise HTTPException(status_code=401, detail="Token de Supabase inválido: falta 'sub'")

        supabase_uuid = uuid.UUID(supabase_id_str)

        user = db.query(User).filter(
            or_(User.email == email, User.supabase_id == supabase_uuid)
        ).first()

        if user:
            if user.supabase_id != supabase_uuid:
                user.supabase_id = supabase_uuid
            if user.email != email:
                user.email = email
        else:
            try:
                initial_role = "ADMIN" if email == "admin@geomaps.com" or email.endswith("@geomaps.com") else "USER"
                user = User(
                    supabase_id=supabase_uuid,
                    email=email,
                    full_name=user_metadata.get("full_name") or user_metadata.get("name") or email.split("@")[0],
                    avatar_url=user_metadata.get("avatar_url") or user_metadata.get("picture"),
                    auth_provider="google" if payload.get("app_metadata", {}).get("provider") == "google" else "supabase",
                    role=initial_role,
                    is_active=True
                )
                db.add(user)
                db.flush()
                logger.info(f"Usuario {email} creado con rol {initial_role}")
            except Exception as e:
                db.rollback()
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
        db.flush()

        access_token = create_access_token(subject={
            "sub": str(user.id),
            "sid": str(session.id),
            "type": "user_session"
        })

        user.last_login = get_utc_now()
        db.commit()

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


auth_service = AuthService()
