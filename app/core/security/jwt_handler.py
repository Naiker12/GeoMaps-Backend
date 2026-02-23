from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from jose import JWTError, jwt
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

def decode_supabase_token(token: str) -> Optional[Dict]:
    """
    Decodifica un token JWT de Supabase.
    Supabase firma sus tokens con el JWT Secret que puede estar en base64.
    Intenta múltiples estrategias para decodificar correctamente.
    """
    import base64
    import binascii

    secret_raw = settings.SUPABASE_JWT_SECRET

    # Estrategia 1: usar el secret tal cual (string)
    try:
        payload = jwt.decode(
            token,
            secret_raw,
            algorithms=["HS256"],
            options={"verify_aud": False, "verify_iat": False, "verify_exp": True}
        )
        return payload
    except JWTError as e1:
        logger.debug(f"decode_supabase_token: intento 1 (raw string) falló: {e1}")

    # Estrategia 2: intentar decodificar base64 estándar
    try:
        # Añadir padding si es necesario
        padded = secret_raw + "=" * (4 - len(secret_raw) % 4) if len(secret_raw) % 4 else secret_raw
        decoded_secret = base64.b64decode(padded)
        payload = jwt.decode(
            token,
            decoded_secret,
            algorithms=["HS256"],
            options={"verify_aud": False, "verify_iat": False, "verify_exp": True}
        )
        return payload
    except (binascii.Error, ValueError, JWTError) as e2:
        logger.debug(f"decode_supabase_token: intento 2 (base64 std) falló: {e2}")

    # Estrategia 3: intentar decodificar base64 URL-safe
    try:
        # Reemplazar + con - y / con _ para URL-safe base64
        url_safe_secret = secret_raw.replace('+', '-').replace('/', '_').rstrip('=')
        decoded_secret = base64.urlsafe_b64decode(url_safe_secret + "==")
        payload = jwt.decode(
            token,
            decoded_secret,
            algorithms=["HS256"],
            options={"verify_aud": False, "verify_iat": False, "verify_exp": True}
        )
        return payload
    except (binascii.Error, ValueError, JWTError) as e3:
        logger.debug(f"decode_supabase_token: intento 3 (base64 url-safe) falló: {e3}")

    logger.warning(f"decode_supabase_token: Todas las estrategias fallaron para el token.")
    return None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """
    Crea un token JWT interno para administradores.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_internal_token(token: str) -> Optional[Dict]:
    """
    Decodifica un token JWT interno usando el secreto de la aplicación.
    """
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET, 
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None
