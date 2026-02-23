import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
import json
from sqlalchemy.orm import Session
from app.domain.models.user import User
from app.domain.models.admin import Admin
from app.schemas.auth_schema import AuthResponse, UserBase
from app.core.config import settings
from app.core.security.password import verify_password
from app.core.security.jwt_handler import create_access_token
from supabase import create_client, Client

class AuthService:
    def __init__(self):
        self.supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

    async def send_magic_link(self, email: str) -> AuthResponse:
        """
        Envía un enlace mágico al correo del usuario usando Supabase Auth.
        """
        try:
            response = self.supabase.auth.sign_in_with_otp({
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

    async def login_admin(self, email: str, password: str, db: Session) -> AuthResponse:
        """
        Login tradicional con contraseña para Administradores desde la base local.
        """
        try:
            admin = db.query(Admin).filter(Admin.email == email).first()
            if not admin:
                print(f"Login failed: Admin with email {email} not found")
                return AuthResponse(success=False, message="Credenciales inválidas")
            
            if not admin.is_active:
                print(f"Login failed: Admin {email} is not active")
                return AuthResponse(success=False, message="Cuenta de administrador desactivada")

            print(f"Verifying password for {email}...")
            is_valid = verify_password(password, admin.password_hash)
            print(f"Password valid: {is_valid}")
            
            if not is_valid:
                return AuthResponse(success=False, message="Contraseña incorrecta")

            # Generamos JWT interno
            access_token = create_access_token(data={
                "sub": str(admin.id),
                "email": admin.email,
                "role": "SUPER_ADMIN" if admin.is_superadmin else "ADMIN",
                "type": "admin_session"
            })

            return AuthResponse(
                success=True,
                access_token=access_token,
                user=UserBase(
                    id=str(admin.id),
                    email=admin.email,
                    full_name="Administrator",
                    role="SUPER_ADMIN" if admin.is_superadmin else "ADMIN",
                    avatar_url=None
                )
            )
        except Exception as e:
            return AuthResponse(success=False, message=f"Error en login admin: {str(e)}")

    def sync_supabase_user(self, payload: dict, db: Session) -> User:
        """
        Sincroniza el usuario de Supabase con la base de datos local.
        Asegura que el UUID sea el mismo y gestiona roles/metadatos.
        """
        user_id_str = payload.get("sub")
        email = payload.get("email")
        metadata = payload.get("user_metadata", {})

        if not user_id_str or not email:
             raise Exception("Invalid Supabase token payload")

        user_uuid = uuid.UUID(user_id_str)
        
        # 1. Buscar por ID (UUID compartido)
        user = db.query(User).filter(User.id == user_uuid).first()
        
        if not user:
            # 2. Si no existe por ID, verificar por email (posible migración o primer login)
            user = db.query(User).filter(User.email == email).first()
            if user:
                # Si existe por email pero no tiene el ID de Supabase, lo actualizamos (Vínculo Profesional)
                user.id = user_uuid
            else:
                # 3. Crear usuario nuevo con el ID de Supabase
                user = User(
                    id=user_uuid,
                    email=email,
                    full_name=metadata.get("full_name") or metadata.get("name") or "",
                    avatar_url=metadata.get("avatar_url") or metadata.get("picture"),
                    role="user",
                    provider="google",
                    is_active=True
                )
                db.add(user)
        else:
            # 4. Actualizar metadatos si ya existe
            user.full_name = metadata.get("full_name") or metadata.get("name") or user.full_name
            user.avatar_url = metadata.get("avatar_url") or metadata.get("picture") or user.avatar_url
        
        user.last_login = datetime.now(timezone.utc)
        
        try:
            db.commit()
            db.refresh(user)
        except Exception as e:
            db.rollback()
            raise Exception(f"Error syncing user: {str(e)}")
            
        return user

auth_service = AuthService()
