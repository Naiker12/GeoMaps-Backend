"""Dependencias de seguridad para protección de rutas.

Provee validación de tokens y control de acceso basado en roles.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.identity import resolve_token_user
from app.db.models.user import User
from app.db.session import get_db

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Valida el token de autenticación (Local o Supabase) y retorna el usuario."""
    return await resolve_token_user(db, _extract_token(request))


def require_role(allowed_roles: list[str]):
    """Crea una dependencia que restringe acceso por roles.

    Uso: ``Depends(require_role(["ADMIN", "SUPER_ADMIN"]))``
    """

    async def role_dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        user_role = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        allowed_upper = {r.upper() for r in allowed_roles}
        if user_role.upper() not in allowed_upper:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos suficientes para realizar esta acción",
            )
        return current_user

    return role_dependency


# Shortcuts para roles frecuentes
require_admin = require_role(["ADMIN", "SUPER_ADMIN"])
require_super_admin = require_role(["SUPER_ADMIN"])


# ───── Helpers privados ─────


def _extract_token(request: Request) -> str | None:
    """Extrae el token Bearer del header o de cookies."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1]
    return request.cookies.get("access_token")
