from fastapi import APIRouter, Depends, Response, Request, HTTPException
from sqlalchemy.orm import Session
from app.core.security.dependencies import get_current_user
from app.domain.models.user import User
from app.schemas.user_schema import UserBase
from app.core.config import settings
from pydantic import BaseModel
from app.infrastructure.database.session import get_db
from app.application.auth.service import auth_service
from app.core.security.jwt_handler import decode_supabase_token

router = APIRouter(prefix="/auth", tags=["auth"])

class SupabaseLoginRequest(BaseModel):
    access_token: str

@router.post("/login/supabase", response_model=UserBase)
async def login_supabase(
    body: SupabaseLoginRequest, 
    response: Response,
    request: Request,
    db: Session = Depends(get_db)
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

        user, local_token = auth_service.start_user_session(
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
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/me", response_model=UserBase)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Retorna la información del usuario autenticado actual desde el token de Supabase.
    """
    return current_user

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
