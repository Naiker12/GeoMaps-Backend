"""Dependencias de inyección para rutas de la API.

Provee autenticación, autorización, y servicios compartidos
mediante el sistema de Depends de FastAPI.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security.api_key_rate_limit import enforce_api_key_rate_limit
from app.core.security.identity import ensure_active_user, resolve_token_user
from app.core.utils.datetime import get_utc_now
from app.db.models.user import User, UserRole
from app.db.session import get_db

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
    return await resolve_token_user(db, token or request.cookies.get("access_token"))


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

    from sqlalchemy.orm import selectinload

    from app.db.models.api_key import APIKey, APIKeyStatus

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if getattr(request.state, "authenticated_api_key_hash", None) == key_hash:
        return request.state.authenticated_api_key_user

    result = await db.execute(
        select(APIKey)
        .where(APIKey.key_hash == key_hash, APIKey.status == APIKeyStatus.ACTIVE)
        .options(selectinload(APIKey.user))
    )
    db_key = result.scalar_one_or_none()

    if not db_key:
        raise HTTPException(status_code=401, detail="API Key inválida o revocada")

    # Proveer estado para el middleware de logs INMEDIATAMENTE después de validar la key
    # para que si falla un límite de cuota u otra validación, el log tenga el user_id.
    request.state.api_key_id = db_key.id
    request.state.user_id = db_key.user_id

    if db_key.expires_at is not None and db_key.expires_at <= get_utc_now():
        raise HTTPException(status_code=401, detail="API Key expirada")
    user = ensure_active_user(db_key.user)

    # Validar Cuota Diaria Restrictiva (10 peticiones/día)
    from app.services.api_keys import APIKeyService

    service = APIKeyService(db)
    has_quota = await service.check_daily_quota(db_key.user_id)
    if not has_quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Límite de cuota diaria alcanzado para esta API Key.",
        )

    await enforce_api_key_rate_limit(db_key.id, db_key.rate_limit_rpm)

    reservation_id = await service.reserve_daily_quota(
        api_key_id=db_key.id, user_id=db_key.user_id,
        endpoint=request.url.path, method=request.method,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    if reservation_id is None:
        raise HTTPException(429, detail="Límite de cuota diaria alcanzado para esta API Key.")
    request.state.api_key_quota_reservation_id = reservation_id

    # Actualizar último uso
    db_key.last_used = get_utc_now()
    await db.commit()
    request.state.authenticated_api_key_hash = key_hash
    request.state.authenticated_api_key_user = user

    # db_key.user ya está cargado por selectinload — NO hace lazy load
    return user


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
        except HTTPException as exc:
            api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            if exc.status_code != 401 or not api_key:
                raise

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
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if api_key:
        # NO envolver en try/except: si la key es inválida, lanzar 401
        return await get_user_from_api_key(request, db)

    # 2. Bearer Token / Cookie — si no hay nada, retornar None
    effective_token = token or request.cookies.get("access_token")
    if not effective_token:
        return None

    try:
        return await resolve_token_user(db, effective_token)
    except HTTPException as exc:
        if exc.status_code in (401, 404):
            return None
        raise


async def get_current_active_user(
    current_user: User = Depends(get_current_user_unified),
) -> User:
    """Asegura que el usuario esté activo."""
    return ensure_active_user(current_user)


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
