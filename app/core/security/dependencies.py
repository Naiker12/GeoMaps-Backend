from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List

from app.infrastructure.database.session import get_db
from app.domain.models.user import User
from app.core.security.jwt_handler import decode_supabase_token

import uuid
from sqlalchemy import or_

async def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Valida el token de Supabase y retorna el usuario de la tabla pública.
    Busca el token en el header Authorization o en la cookie 'access_token'.
    """
    auth_header = request.headers.get("Authorization")
    token = None
    
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        # Fallback a cookie
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se proporcionó un token de autenticación"
        )

    payload = decode_supabase_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado"
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El token no contiene el ID de usuario (sub)"
        )

    try:
        user_uuid = uuid.UUID(user_id)
        user = db.query(User).filter(
            or_(User.id == user_uuid, User.supabase_id == user_uuid)
        ).first()
    except ValueError:
        user = None

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no registrado en la base de datos pública"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario está desactivada"
        )

    return user

def require_role(allowed_roles: List[str]):
    """
    Dependencia para proteger rutas basado en roles.
    Uso: Depends(require_role(["ADMIN", "SUPER_ADMIN"]))
    """
    async def role_dependency(current_user: User = Depends(get_current_user)):
        # Convertimos el rol a string para la comparación si es un Enum
        user_role = str(current_user.role.value) if hasattr(current_user.role, 'value') else str(current_user.role)
        if user_role.upper() not in [r.upper() for r in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos suficientes para realizar esta acción"
            )
        return current_user
    return role_dependency

# Versiones rápidas para roles comunes (Usando mayúsculas coherentes con la DB)
require_admin = require_role(["ADMIN", "SUPER_ADMIN"])
require_super_admin = require_role(["SUPER_ADMIN"])
