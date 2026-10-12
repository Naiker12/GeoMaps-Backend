"""JWT locales y Supabase con algoritmos y claims explícitos."""

import base64
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from authlib.jose import JoseError, JsonWebKey, JsonWebToken

from app.core.config import settings

logger = logging.getLogger(__name__)
LOCAL_ISSUER = "geomaps"
MAX_TOKEN_LENGTH = 16_384
JWKS_TTL_SECONDS = 600
JWKS_RETRY_SECONDS = 60
_jwt_hs = JsonWebToken(["HS256"])
_jwt_asymmetric = JsonWebToken(["ES256", "RS256"])
_supabase_jwks: dict[str, Any] = {}
_last_jwks_fetch: float | None = None
_last_jwks_attempt: float | None = None
_jwks_lock = threading.Lock()


def _get_supabase_public_key(kid: str) -> dict[str, Any] | None:
    """Cache por proceso; limita recargas por kids desconocidos y fallos de red.

    Los consumidores asíncronos ejecutan la verificación en el thread pool.
    No se reutilizan llaves cuya cache superó diez minutos si falla la recarga.
    """
    global _supabase_jwks, _last_jwks_fetch, _last_jwks_attempt
    with _jwks_lock:
        now = time.monotonic()
        fresh = _last_jwks_fetch is not None and now - _last_jwks_fetch < JWKS_TTL_SECONDS
        if fresh and kid in _supabase_jwks:
            return _supabase_jwks[kid]
        if _last_jwks_attempt is not None and now - _last_jwks_attempt < JWKS_RETRY_SECONDS:
            return _supabase_jwks.get(kid) if fresh else None
        _last_jwks_attempt = now
        url = f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1/.well-known/jwks.json"
        try:
            response = httpx.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            keys = data.get("keys") if isinstance(data, dict) else None
            if not isinstance(keys, list):
                raise ValueError("Respuesta JWKS inválida")
            updated = {
                key["kid"]: key for key in keys
                if isinstance(key, dict) and isinstance(key.get("kid"), str)
                and key.get("kty") in ("EC", "RSA")
            }
            _supabase_jwks = updated
            _last_jwks_fetch = time.monotonic()
            return updated.get(kid)
        except (httpx.HTTPError, ValueError, TypeError, RecursionError):
            logger.warning("No se pudo actualizar la cache JWKS de Supabase")
            return _supabase_jwks.get(kid) if fresh else None


def _read_header(token: str) -> dict[str, Any]:
    if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
        raise ValueError("Token inválido")
    parts = token.split(".")
    if len(parts) != 3 or not all(parts) or len(parts[0]) > 2048:
        raise ValueError("Formato JWT inválido")
    header = json.loads(base64.b64decode(parts[0] + "=" * (-len(parts[0]) % 4), altchars=b"-_", validate=True))
    if not isinstance(header, dict):
        raise ValueError("Header JWT inválido")
    return header


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    if not settings.SECRET_KEY:
        raise RuntimeError("SECRET_KEY no está configurado")
    now = datetime.now(timezone.utc)
    lifetime = expires_delta if expires_delta is not None else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {**data, "iss": LOCAL_ISSUER, "iat": now, "exp": now + lifetime}
    return _jwt_hs.encode({"alg": "HS256"}, payload, settings.SECRET_KEY.encode()).decode("utf-8")


def decode_supabase_token(token: str) -> dict[str, Any] | None:
    try:
        header = _read_header(token)
        alg = header.get("alg")
        options = {
            "exp": {"essential": True}, "sub": {"essential": True},
            "iss": {"essential": True, "value": settings.SUPABASE_JWT_ISSUER or f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1"},
            "aud": {"essential": True, "value": "authenticated"},
        }
        if alg == "HS256":
            if not settings.SUPABASE_JWT_SECRET:
                return None
            # El secreto es texto literal, incluso si parece una cadena Base64.
            claims = _jwt_hs.decode(token, settings.SUPABASE_JWT_SECRET.encode(), claims_options=options)
        elif alg in ("ES256", "RS256"):
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > 256:
                return None
            key = _get_supabase_public_key(kid)
            if key is None or key.get("alg", alg) != alg:
                return None
            claims = _jwt_asymmetric.decode(token, JsonWebKey.import_key(key), claims_options=options)
        else:
            return None
        claims.validate()
        return dict(claims)
    except (JoseError, ValueError, TypeError, KeyError, RecursionError):
        return None


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        if not settings.SECRET_KEY or _read_header(token).get("alg") != "HS256":
            return None
        claims = _jwt_hs.decode(token, settings.SECRET_KEY.encode(), claims_options={
            "exp": {"essential": True}, "sub": {"essential": True},
            # Tokens locales históricos sin iss conservan compatibilidad.
            "iss": {"validate": lambda claims, value: value is None or value == LOCAL_ISSUER},
        })
        claims.validate()
        return dict(claims)
    except (JoseError, ValueError, TypeError, KeyError, RecursionError):
        return None
