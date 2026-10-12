"""Resolución de identidad JWT compartida por las dependencias HTTP."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.jwt_handler import decode_supabase_token, decode_token
from app.core.utils.datetime import get_utc_now
from app.db.models.user import User
from app.db.models.user_session import UserSession


def ensure_active_user(user: User) -> User:
    """Evita que una cuenta desactivada se use como identidad autenticada."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario está desactivada",
        )
    return user


async def resolve_token_user(db: AsyncSession, token: str | None) -> User:
    """Valida credenciales; los errores de persistencia conservan su causa."""
    if not token:
        raise HTTPException(status_code=401, detail="No se proporcionó un token de autenticación")

    payload = await run_in_threadpool(decode_token, token)
    is_local = payload is not None
    if payload is None:
        payload = await run_in_threadpool(decode_supabase_token, token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=401, detail="Identidad de usuario inválida") from exc

    result = await db.execute(
        select(User).where(User.id == user_id if is_local else User.supabase_id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no registrado en la base de datos local")
    ensure_active_user(user)
    if "sid" in payload:
        try:
            session_id = uuid.UUID(str(payload["sid"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(status_code=401, detail="Identidad de sesión inválida") from exc
        session_result = await db.execute(
            select(UserSession.id).where(
                UserSession.id == session_id,
                UserSession.user_id == user.id,
                UserSession.logout_at.is_(None),
                UserSession.expires_at > get_utc_now(),
            )
        )
        if session_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=401, detail="Sesión revocada o expirada")
    return user
