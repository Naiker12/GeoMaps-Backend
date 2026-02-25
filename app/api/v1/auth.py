from fastapi import APIRouter, Depends, Response
from app.core.security.dependencies import get_current_user
from app.domain.models.user import User
from app.schemas.user_schema import UserBase
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

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
