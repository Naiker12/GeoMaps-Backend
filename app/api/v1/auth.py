"""Router de autenticación V1.
Coordina Supabase, cookies seguras y sesiones de usuario.
"""

import logging
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth.service import auth_service
from app.core.config import settings
from app.core.security.dependencies import get_current_user
from app.core.security.jwt_handler import decode_supabase_token
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth_schema import SessionResponse
from app.schemas.user_schema import UserBase, UserUpdate
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class SupabaseLoginRequest(BaseModel):
    access_token: str


@router.post("/login/supabase", response_model=UserBase)
async def login_supabase(
    body: SupabaseLoginRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Sincroniza el login de Supabase con el servidor backend mediante cookies HttpOnly."""
    try:
        payload = decode_supabase_token(body.access_token)
        if not payload:
            raise HTTPException(
                status_code=401, detail="Token Supabase inválido o expirado"
            )

        # Iniciar sesión localmente (sincroniza perfil y genera access_token backend)
        user, local_token = await auth_service.start_user_session(
            payload=payload,
            db=db,
            ip=request.client.host if request.client else None,
            ua=request.headers.get("user-agent"),
        )

        is_dev = (
            "localhost" in settings.FRONTEND_URL or "127.0.0.1" in settings.FRONTEND_URL
        )

        # Token backend en cookie HttpOnly (más seguro que localStorage)
        response.set_cookie(
            key="access_token",
            value=local_token,
            httponly=True,
            samesite="lax",
            secure=not is_dev,
            max_age=86400,
        )

        # PERSISTIR CAMBIOS (Importante!)
        await db.commit()
        await db.refresh(user)

        return user

    except Exception as exc:
        logger.error("Error en login_supabase: %s", exc)
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(
            status_code=400, detail=f"Fallo en autenticación backend: {exc}"
        )


@router.get("/me", response_model=UserBase)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Obtiene el perfil del usuario autenticado actual."""
    return current_user


@router.patch("/me", response_model=UserBase)
async def update_my_profile(
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Actualiza datos del perfil (nombre, avatar, bio, etc)."""
    user = await auth_service.update_user_profile(db, current_user, user_update)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/me/avatar", response_model=UserBase)
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sube una imagen y la establece como avatar del usuario."""
    url = await storage_service.upload_file(file, "profiles")
    update = UserUpdate(avatar_url=url)
    user = await auth_service.update_user_profile(db, current_user, update)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/logout")
async def logout(response: Response):
    """Limpia las cookies de autenticación del navegador."""
    is_dev = (
        "localhost" in settings.FRONTEND_URL or "127.0.0.1" in settings.FRONTEND_URL
    )
    response.delete_cookie(
        key="access_token",
        path="/",
        httponly=True,
        samesite="lax",
        secure=not is_dev,
    )
    return {"success": True}


@router.get("/sessions", response_model=list[SessionResponse])
async def get_my_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista las sesiones activas del usuario para gestión de dispositivos."""
    sessions = await auth_service.get_active_sessions(current_user.id, db)
    return [
        SessionResponse(
            id=s.id,
            device=_detect_device(s.user_agent),
            location=s.ip_address or "IP Desconocida",
            last_active=s.login_at,
            is_current=False,  # Implementar comparación con SID del token si es necesario
        )
        for s in sessions
    ]


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invalida una sesión de dispositivo específica."""
    if not await auth_service.revoke_session(session_id, current_user.id, db):
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return {"success": True}


def _detect_device(ua: str | None) -> str:
    """Extrae nombre legible del dispositivo desde el User-Agent."""
    if not ua:
        return "Sesión remota"

    device = "Dispositivo"
    for keyword in ["Windows", "iPhone", "Android", "Macintosh"]:
        if keyword in ua:
            device = keyword if keyword != "Macintosh" else "Mac"
            break

    browser = "Navegador"
    for b in ["Chrome", "Safari", "Firefox", "Edg"]:
        if b in ua:
            browser = b if b != "Edg" else "Edge"
            break

    return f"{browser} en {device}"
