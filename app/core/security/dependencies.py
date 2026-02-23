from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import uuid
import logging
from datetime import datetime, timezone

from app.core.security.jwt_handler import decode_supabase_token, decode_internal_token
from app.infrastructure.database.session import get_db
from app.domain.models.user import User
from app.domain.models.admin import Admin

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

async def get_current_user(
    auth: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Dependencia para Usuarios Finales (Google/Magic Link via Supabase).
    Valida el JWT de Supabase y sincroniza/crea en la tabla 'users'.
    """
    if not auth:
        logger.warning("get_current_user: No se recibió Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere token de acceso",
        )
    
    token_preview = auth.credentials[:30] + "..." if len(auth.credentials) > 30 else auth.credentials
    logger.info(f"get_current_user: Validando token (preview): {token_preview}")
    
    payload = decode_supabase_token(auth.credentials)
    if not payload:
        logger.error(f"get_current_user: decode_supabase_token retornó None para token: {token_preview}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión expirada o token inválido",
        )
    
    logger.info(f"get_current_user: Token válido para sub={payload.get('sub')}, email={payload.get('email')}")
    
    try:
        from app.application.auth.service import auth_service
        user = auth_service.sync_supabase_user(payload, db)
    except Exception as e:
        logger.error(f"get_current_user: sync_supabase_user falló: {e}")
        raise HTTPException(status_code=500, detail=f"Error al sincronizar usuario: {str(e)}")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Cuenta desactivada")

    return user

async def get_current_admin(
    auth: HTTPAuthorizationCredentials = Depends(security),
    admin_token: str | None = Cookie(None),
    db: Session = Depends(get_db)
):
    """
    Dependencia para Administradores (Email/Password).
    Valida el JWT interno (via header o cookie) y verifica en la tabla 'admins'.
    """
    token = None
    if auth:
        token = auth.credentials
    elif admin_token:
        token = admin_token

    if not token:
        raise HTTPException(status_code=401, detail="Se requiere acceso de administrador")
    
    payload = decode_internal_token(token)
    if not payload or payload.get("type") != "admin_session":
        raise HTTPException(status_code=401, detail="Sesión de administrador inválida")
    
    admin_id = payload.get("sub")
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    
    if not admin or not admin.is_active:
        raise HTTPException(status_code=403, detail="Acceso denegado o cuenta inactivada")
    
    return admin

async def get_current_super_admin(current_admin: Admin = Depends(get_current_admin)):
    """
    Verifica que el administrador sea Super Admin.
    """
    if not current_admin.is_superadmin:
        raise HTTPException(status_code=403, detail="Se requieren permisos de Súper Administrador")
    return current_admin
