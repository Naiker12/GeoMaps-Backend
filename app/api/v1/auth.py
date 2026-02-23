from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from sqlalchemy.orm import Session
from app.infrastructure.database.session import get_db
from app.schemas.auth_schema import UserBase, MagicLinkRequest, AdminLoginRequest, AuthResponse
from app.application.auth.service import auth_service
from app.core.config import settings
from app.core.security.dependencies import get_current_user, get_current_admin

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/magic-link", response_model=AuthResponse)
async def send_magic_link(request: MagicLinkRequest):
    """
    Envía un enlace de activación (Magic Link) al correo del usuario.
    """
    return await auth_service.send_magic_link(request.email)

@router.post("/admin/login", response_model=AuthResponse)
async def admin_login(
    request: AdminLoginRequest, 
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Login tradicional con contraseña para Administradores.
    Valida contra la base de datos local y genera un JWT interno que se guarda en cookie HttpOnly.
    """
    res = await auth_service.login_admin(request.email, request.password, db)
    if not res.success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=res.message
        )
    
    # Establecer la cookie HttpOnly
    # secure=True solo en producción (HTTPS); en localhost HTTP debe ser False
    is_production = not settings.FRONTEND_URL.startswith("http://localhost")
    response.set_cookie(
        key="admin_token",
        value=res.access_token,
        httponly=True,
        secure=is_production,
        samesite="lax",
        max_age=60 * 60 * 24  # 24 horas
    )
    
    return res

@router.post("/admin/logout")
async def admin_logout(response: Response):
    """
    Cierra la sesión del administrador eliminando la cookie.
    """
    response.delete_cookie(key="admin_token")
    return {"success": True, "message": "Sesión cerrada"}

@router.get("/me", response_model=UserBase)
async def get_me(current_user=Depends(get_current_user)):
    """
    Retorna la información del usuario final actual autenticado via Supabase.
    Realiza la sincronización automática con la base local.
    """
    return UserBase(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        avatar_url=current_user.avatar_url
    )

@router.get("/admin/me", response_model=UserBase)
async def get_admin_me(current_admin=Depends(get_current_admin)):
    """
    Retorna la información del administrador actual autenticado via JWT interno.
    """
    return UserBase(
        id=str(current_admin.id),
        email=current_admin.email,
        full_name="Administrator",
        role="SUPER_ADMIN" if current_admin.is_superadmin else "ADMIN",
        avatar_url=None
    )

@router.post("/debug-token")
async def debug_token(request: dict):
    """
    Endpoint temporal de diagnóstico para verificar decodificación de tokens Supabase.
    TODO: Eliminar en producción.
    """
    from fastapi import Request
    from app.core.security.jwt_handler import decode_supabase_token
    token = request.get("token", "")
    payload = decode_supabase_token(token)
    if payload:
        return {
            "status": "ok",
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "exp": payload.get("exp"),
        }
    return {"status": "error", "detail": "Token inválido o expirado - ver logs del backend"}

