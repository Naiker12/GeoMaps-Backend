"""Dependencias de seguridad para protección de rutas.

Provee validación de tokens y control de acceso basado en roles.
"""

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.Geo_Usuarios.model import User
from app.shared.db.session import get_db

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Valida el token de autenticación (Local o Supabase) y retorna el usuario."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se proporcionó un token de autenticación",
        )

    # Intentar decodificar con el secreto local (tokens emitidos por este backend)
    from app.core.security.jwt_handler import decode_token, decode_supabase_token
    payload = decode_token(token)
    
    # Si falla, intentar decodificar como token de Supabase (frontend directo)
    if not payload:
        payload = decode_supabase_token(token)
        
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido, expirado o secreto no coincide",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El token no contiene el ID de usuario (sub)",
        )

    user = await _find_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no registrado en la base de datos pública",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario está desactivada",
        )

    return user


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
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]
    return request.cookies.get("access_token")


async def _find_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    """Busca un usuario por su UUID en la tabla pública."""
    try:
        user_uuid = uuid.UUID(user_id)
        result = await db.execute(
            select(User).where(or_(User.id == user_uuid, User.supabase_id == user_uuid))
        )
        return result.scalar_one_or_none()
    except ValueError:
        return None
