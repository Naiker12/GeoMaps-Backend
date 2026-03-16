from fastapi import APIRouter, Depends, Response, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security.dependencies import get_current_user
from app.db.models.user import User
from app.schemas.user_schema import UserBase, UserUpdate
from app.core.config import settings
from pydantic import BaseModel
from app.db.session import get_db
import uuid
from app.application.auth.service import auth_service
from app.core.security.jwt_handler import decode_supabase_token
from app.schemas.auth_schema import SessionResponse
from app.services.storage_service import storage_service
from fastapi import UploadFile, File
from typing import List
import logging
import traceback

logger = logging.getLogger(__name__)
import logging
import traceback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

class SupabaseLoginRequest(BaseModel):
    access_token: str

@router.post("/login/supabase", response_model=UserBase)
async def login_supabase(
    body: SupabaseLoginRequest, 
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Sincroniza la sesión de Supabase con el backend.
    """
    try:
        payload = decode_supabase_token(body.access_token)
        if not payload:
            raise HTTPException(status_code=401, detail="Token no es válido o ha expirado")
            
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        # Nota: auth_service.start_user_session debe ser asíncrono o manejado correctamente
        # Por ahora lo mantenemos asumiendo que db es AsyncSession y el servicio lo soporta
        user, local_token = await auth_service.start_user_session(
            payload=payload, 
            db=db, 
            ip_address=ip_address, 
            user_agent=user_agent
        )

        is_dev = "localhost" in settings.FRONTEND_URL or "127.0.0.1" in settings.FRONTEND_URL
        response.set_cookie(
            key="access_token",
            value=local_token or body.access_token,
            httponly=True,
            samesite="lax",
            secure=not is_dev,
            max_age=86400
        )
        return user
    except Exception as e:
        logger.error(f"Error en login_supabase: {str(e)}")
        logger.error(traceback.format_exc())
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=400, 
            detail=f"Error en sincronización de servidor: {str(e)}"
        )

@router.get("/me", response_model=UserBase)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """
    Retorna la información del usuario autenticado actual desde el token de Supabase.
    """
    return current_user

@router.patch("/me", response_model=UserBase)
async def update_my_profile(
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza el perfil del usuario autenticado.
    """
    updated_user = await auth_service.update_user_profile(db, current_user, user_update)
    return updated_user

@router.post("/me/avatar", response_model=UserBase)
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Sube una imagen de perfil para el usuario actual.
    """
    public_url = await storage_service.upload_file(file, bucket_type="images")
    
    # Actualizar el usuario en la base de datos
    user_update = UserUpdate(avatar_url=public_url)
    updated_user = await auth_service.update_user_profile(db, current_user, user_update)
    
    return updated_user

@router.post("/logout")
async def logout(response: Response):
    """
    Cierra la sesión en el servidor invalidando las cookies de autenticación.
    """
    try:
        # Detectamos si estamos en desarrollo para el flag 'secure'
        is_dev = "localhost" in settings.FRONTEND_URL or "127.0.0.1" in settings.FRONTEND_URL
        
        # 1. Borramos la cookie access_token (HttpOnly)
        response.delete_cookie(
            key="access_token",
            path="/",
            httponly=True,
            samesite="lax",
            secure=not is_dev  # False en localhost para que funcione sin HTTPS
        )
        
        return {
            "success": True, 
            "message": "Cierre de sesión de servidor exitoso"
        }
    except Exception as e:
        return {
            "success": False, 
            "message": f"Error parcial en servidor: {str(e)}"
        }

@router.get("/sessions", response_model=List[SessionResponse])
async def get_my_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Lista las sesiones activas del usuario con detección básica de dispositivo.
    """
    sessions = await auth_service.get_active_sessions(current_user.id, db)
    
    # Extraer sid del token actual para marcar 'is_current'
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        token = request.cookies.get("access_token")
    
    current_sid = None
    if token:
        payload = decode_supabase_token(token)
        if payload:
            current_sid = payload.get("sid")

    response_data = []
    for s in sessions:
        ua = s.user_agent if s.user_agent else ""
        device_name = "Dispositivo"
        if "Windows" in ua: device_name = "Windows PC"
        elif "iPhone" in ua: device_name = "iPhone"
        elif "Android" in ua: device_name = "Android"
        elif "Macintosh" in ua: device_name = "Mac"
        
        if "Chrome" in ua: browser = "Chrome"
        elif "Safari" in ua: browser = "Safari"
        elif "Firefox" in ua: browser = "Firefox"
        elif "Edg" in ua: browser = "Edge"
        else: browser = ""

        full_device = f"{browser} en {device_name}" if browser else device_name

        response_data.append(SessionResponse(
            id=s.id,
            device=full_device if ua else "Sesión remota",
            location=s.ip_address if s.ip_address else "IP Desconocida",
            last_active=s.login_at,
            is_current=str(s.id) == str(current_sid)
        ))
    
    return response_data

@router.delete("/sessions/{session_id}")
async def revoke_user_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Revoca una sesión específica.
    """
    success = await auth_service.revoke_session(session_id, current_user.id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return {"success": True}
