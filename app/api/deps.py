"""Dependencias de inyección para rutas de la API.

Provee autenticación, autorización, y servicios compartidos
mediante el sistema de Depends de FastAPI.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security.identity import ensure_active_user, resolve_token_user
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


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(oauth2_scheme_optional),
) -> User | None:
    """Resuelve la sesión JWT/cookie; sin sesión retorna un usuario anónimo."""
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
    current_user: User = Depends(get_current_user),
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
