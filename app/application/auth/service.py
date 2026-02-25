import uuid
import logging
from datetime import timedelta
from typing import Optional
from sqlalchemy.orm import Session
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
        self.supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

    async def send_magic_link(self, email: str) -> AuthResponse:
        """
        Envía un enlace mágico al correo del usuario usando Supabase Auth.
        """
        try:
            self.supabase.auth.sign_in_with_otp({
                "email": email,
                "options": {
                    "should_create_user": True,
                    "email_redirect_to": f"{settings.FRONTEND_URL}/Midas-Frontend/auth/callback"
                }
            })
            return AuthResponse(
                success=True, 
                message="Enlace de activación enviado. Revisa tu correo."
            )
        except Exception as e:
            return AuthResponse(success=False, message=str(e))

    async def login_admin(self, email: str, password: str, db: Session, ip_address: str = None, user_agent: str = None) -> AuthResponse:
        """
        Login tradicional para Administradores con control estricto de sesión en UTC.
        """
        try:
            admin = db.query(Admin).filter(Admin.email == email).first()
            if not admin or not admin.is_active:
                return AuthResponse(success=False, message="Credenciales inválidas o cuenta desactivada")
            
            if not verify_password(password, admin.password_hash):
                return AuthResponse(success=False, message="Credenciales inválidas")

            # 1. Crear sesión en base de datos (UTC Aware)
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

            # 2. Generar JWT interno usando el ID de sesión como 'sid'
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
        """
        Sincroniza el usuario de Supabase y crea una sesión local.
        SI el usuario no existe en la tabla local, SE CREA automáticamente.
        """
        supabase_id_str = payload.get("sub")
        email = payload.get("email")
        user_metadata = payload.get("user_metadata", {})

        if not supabase_id_str:
             raise HTTPException(status_code=401, detail="Token de Supabase inválido: falta 'sub'")

        supabase_uuid = uuid.UUID(supabase_id_str)
        
        # 1. Buscar usuario por supabase_id
        user = db.query(User).filter(User.supabase_id == supabase_uuid).first()
        
        if not user:
            logger.info(f"Usuario {email} no encontrado por supabase_id. Buscando por email...")
            # 2. Intentar buscar por email
            user = db.query(User).filter(User.email == email).first()
            if user:
                logger.info(f"Usuario {email} encontrado por email. Vinculando supabase_id...")
                user.supabase_id = supabase_uuid
            else:
                logger.info(f"Creando nuevo usuario local para {email} (Sincronización inicial)")
                # 3. Crear automáticamente (Sincronización)
                try:
                    user = User(
                        supabase_id=supabase_uuid,
                        email=email,
                        full_name=user_metadata.get("full_name") or user_metadata.get("name") or email.split("@")[0],
                        avatar_url=user_metadata.get("avatar_url") or user_metadata.get("picture"),
                        auth_provider="google" if payload.get("app_metadata", {}).get("provider") == "google" else "supabase",
                        is_active=True
                    )
                    db.add(user)
                    db.flush() # Importante: asegura que el usuario tenga ID antes de crear la sesión
                    logger.info(f"Usuario {email} creado exitosamente con ID local {user.id}")
                except Exception as e:
                    db.rollback()
                    logger.error(f"Error crítico creando usuario local: {str(e)}")
                    raise HTTPException(status_code=500, detail="Error al sincronizar perfil de usuario")

        
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Cuenta desactivada")

        # 4. Crear sesión en DB (UTC Aware)
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

        # 5. Generar nuestro propio token de sesión
        access_token = create_access_token(data={
            "sub": str(user.id),
            "sid": str(session.id),
            "type": "user_session"
        })

        user.last_login = get_utc_now()
        db.commit()
        
        return user, access_token

    def invalidate_session(self, session_id: str, db: Session):
        """
        Invalida una sesión en la base de datos usando tiempo UTC.
        """
        try:
            session = db.query(UserSession).filter(UserSession.id == session_id).first()
            if session:
                session.logout_at = get_utc_now()
                db.commit()
        except Exception as e:
            logger.error(f"Error al invalidar sesión: {str(e)}")
            db.rollback()

auth_service = AuthService()
