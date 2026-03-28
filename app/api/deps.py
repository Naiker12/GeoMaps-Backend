"""Dependencias de inyección para rutas de la API.

Provee autenticación, autorización, y servicios compartidos
mediante el sistema de Depends de FastAPI.
"""
import uuid
import logging

logger = logging.getLogger(__name__)

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.db.models.user import User, UserRole
from app.db.session import get_db
from app.repositories.project_repository import ProjectRepository
from app.services.project_service import ProjectService

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
)

oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False,
)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(oauth2_scheme_optional),
) -> User:
    """Valida el token (Local o Supabase) y retorna el usuario autenticado."""
    from app.core.security.jwt_handler import decode_token, decode_supabase_token
    
    effective_token = token or request.cookies.get("access_token")
    if not effective_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se proporcionó un token de autenticación",
        )

    # Priorizar token local
    payload = decode_token(effective_token)
    if not payload:
        # Fallback a token de Supabase
        payload = decode_supabase_token(effective_token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado (Backend & Supabase fallaron)",
        )

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El token no contiene el ID de usuario (sub)",
        )

    try:
        user_uuid = uuid.UUID(user_id)
        result = await db.execute(
            select(User).where(or_(User.id == user_uuid, User.supabase_id == user_uuid))
        )
        user = result.scalar_one_or_none()
    except (ValueError, Exception) as e:
        logger.error(f"Error buscando usuario {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Error al procesar la identidad del usuario",
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no registrado en la base de datos local",
        )

    return user


async def get_user_from_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Valida una API Key enviada en el header X-API-Key o query param."""
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere API Key (X-API-Key header o ?api_key=)",
        )
    
    import hashlib
    from datetime import datetime
    from sqlalchemy.orm import selectinload
    from app.db.models.api_key import APIKey, APIKeyStatus
    
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # CORRECCIÓN CRÍTICA: cargar .user con selectinload para evitar MissingGreenlet
    result = await db.execute(
        select(APIKey)
        .where(APIKey.key_hash == key_hash, APIKey.status == APIKeyStatus.ACTIVE)
        .options(selectinload(APIKey.user))
    )
    db_key = result.scalar_one_or_none()
    
    if not db_key:
        raise HTTPException(status_code=401, detail="API Key inválida o revocada")
    
    # Validar Cuota Diaria Restrictiva (10 peticiones/día)
    from app.services.api_key_service import APIKeyService
    service = APIKeyService(db)
    has_quota = await service.check_daily_quota(db_key.user_id)
    if not has_quota:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="API Rate Limit Exceeded: Daily quota reached.")
    
    # Actualizar último uso
    db_key.last_used = datetime.now()
    await db.commit()
    
    # Proveer estado para el middleware de logs
    request.state.api_key_id = db_key.id
    request.state.user_id = db_key.user_id
    
    # db_key.user ya está cargado por selectinload — NO hace lazy load
    return db_key.user


async def get_current_user_unified(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(oauth2_scheme_optional),
) -> User:
    """Permite autenticación mediante Token JWT (Browser/App) o API Key (Programático)."""
    # Intentar JWT primero
    if token or request.cookies.get("access_token"):
        try:
            return await get_current_user(request, db, token=token)
        except HTTPException:
            pass # Fallthrough if JWT fails
            
    # Intentar API Key
    return await get_user_from_api_key(request, db)


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(oauth2_scheme_optional),
) -> User | None:
    """Retorna el usuario si hay credenciales válidas, None si no hay nada.
    IMPORTANTE: si se envía una API Key inválida, lanza 401 (no silencia).
    """
    # 1. API Key — si se envió, debe ser válida (no degradar a anónimo)
    api_key = (
        request.headers.get("X-API-Key")
        or request.query_params.get("api_key")
    )
    if api_key:
        # NO envolver en try/except: si la key es inválida, lanzar 401
        return await get_user_from_api_key(request, db)

    # 2. Bearer Token / Cookie — si no hay nada, retornar None
    effective_token = token or request.cookies.get("access_token")
    if not effective_token:
        return None

    try:
        from app.core.security.jwt_handler import (
            decode_token, decode_supabase_token
        )
        payload = (
            decode_token(effective_token)
            or decode_supabase_token(effective_token)
        )
        if not payload:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        user_uuid = uuid.UUID(user_id)
        result = await db.execute(
            select(User).where(
                or_(User.id == user_uuid, User.supabase_id == user_uuid)
            )
        )
        return result.scalar_one_or_none()
    except Exception:
        return None


async def get_current_active_user(
    current_user: User = Depends(get_current_user_unified),
) -> User:
    """Asegura que el usuario esté activo."""
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Cuenta de usuario inactiva")
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Asegura que el usuario sea administrador o súper administrador."""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos de administrador para esta acción",
        )
    return current_user


async def get_project_service(
    db: AsyncSession = Depends(get_db),
) -> ProjectService:
    """Inyecta ProjectService con su repositorio."""
    return ProjectService(db)


