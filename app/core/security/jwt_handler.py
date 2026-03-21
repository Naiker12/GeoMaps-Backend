"""Gestión de tokens JWT (JSON Web Tokens).
Implementa firmas de tokens mediante HS256 y verifica las procedentes de Supabase.
Soporta ES256 para nuevos proyectos de Supabase mediante JWKS.
"""

import logging
import base64
import json
import time
import httpx
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from authlib.jose import JoseError, JsonWebToken, JsonWebKey
from app.core.config import settings

logger = logging.getLogger(__name__)

# Instancias específicas para evitar confusiones de tipos de clave en Authlib
_jwt_hs = JsonWebToken(["HS256"])
_jwt_all = JsonWebToken(["HS256", "RS256", "ES256"])

# Cache para las llaves públicas de Supabase (JWKS)
_supabase_jwks: dict[str, Any] = {}
_last_jwks_fetch = 0

def _get_supabase_public_key(kid: str) -> Optional[Any]:
    """Obtiene la llave pública desde el JWKS de Supabase."""
    global _supabase_jwks, _last_jwks_fetch
    
    now = time.time()
    # Refrescar cada 1 hora o si no tenemos la llave solicitada
    if not _supabase_jwks or kid not in _supabase_jwks or (now - _last_jwks_fetch > 3600):
        try:
            # Construir URL del JWKS desde el SUPABASE_URL
            base_url = str(settings.SUPABASE_URL).rstrip("/")
            url = f"{base_url}/auth/v1/.well-known/jwks.json"
            
            logger.info(f"Cargando JWKS desde Supabase: {url}")
            response = httpx.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                _supabase_jwks = {k["kid"]: k for k in data.get("keys", [])}
                _last_jwks_fetch = now
                logger.info(f"JWKS de Supabase actualizado. Kids: {list(_supabase_jwks.keys())}")
            else:
                logger.error(f"Error cargando JWKS: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error inesperado cargando JWKS: {e}")
            
    return _supabase_jwks.get(kid)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Genera un JWT firmado localmente con expiración configurable."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    header = {"alg": "HS256"}
    payload = to_encode
    secret = settings.SECRET_KEY.encode() if isinstance(settings.SECRET_KEY, str) else settings.SECRET_KEY
    
    return _jwt_hs.encode(header, payload, secret).decode("utf-8")


def decode_supabase_token(token: str) -> Optional[dict[str, Any]]:
    """Valida y decodifica un token de Supabase Identity mediante secreto compartido (HS256) o llave pública (ES256)."""
    try:
        # Inspeccionar el header de forma manual para diagnóstico y ruteo
        try:
            parts = token.split(".")
            header_b64 = parts[0]
            missing_padding = len(header_b64) % 4
            if missing_padding:
                header_b64 += "=" * (4 - missing_padding)
            header_json = base64.b64decode(header_b64).decode("utf-8")
            unverified_header = json.loads(header_json)
            alg = unverified_header.get("alg", "HS256")
            kid = unverified_header.get("kid")
        except Exception as e:
            logger.warning(f"No se pudo leer el header del token manual: {e}")
            alg = "HS256"
            kid = None

        # Ruteo según Algoritmo decubierto
        if alg.startswith("HS"):
            secret_str = settings.SUPABASE_JWT_SECRET
            if not secret_str:
                logger.error("Secreto JWT de Supabase no configurado para HS256")
                return None
                
            try:
                # Si parece b64 puro o largo
                if "/" in secret_str or "+" in secret_str or secret_str.endswith("==") or len(secret_str) > 40:
                    secret = base64.b64decode(secret_str)
                else:
                    secret = secret_str.encode()
            except Exception:
                secret = secret_str.encode()
                
            payload_claims = _jwt_hs.decode(token, secret)
        
        elif alg == "ES256" and kid:
            # Caso Asimétrico: Usar JWKS de Supabase
            jwk_data = _get_supabase_public_key(kid)
            if not jwk_data:
                logger.error(f"No se encontró la llave pública en JWKS para kid: {kid}")
                return None
            
            # Importar la llave JWK a un formato asimétrico válido para Authlib
            public_key = JsonWebKey.import_key(jwk_data)
            payload_claims = _jwt_all.decode(token, public_key)
        
        else:
            logger.error(f"Algoritmo {alg} no soportado o falta 'kid' para validación asimétrica")
            return None

        payload_claims.validate()
        return payload_claims
    except JoseError as exc:
        if "expired" in str(exc).lower():
            logger.warning(f"Token de Supabase expirado: {exc}")
        else:
            logger.warning(f"Falla en verificación Supabase ({alg}): {exc}")
        return None
    except Exception as exc:
        logger.error(f"Error inesperado decodificando Supabase: {exc}", exc_info=True)
        return None


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """Valida y decodifica un token generado por el backend de GeoMaps."""
    try:
        secret = settings.SECRET_KEY.encode() if isinstance(settings.SECRET_KEY, str) else settings.SECRET_KEY
        # Localmente SIEMPRE usamos HS256
        payload_claims = _jwt_hs.decode(token, secret)
        payload_claims.validate()
        return payload_claims
    except JoseError as exc:
        if "expired" in str(exc).lower():
            logger.warning(f"Token local expirado: {exc}")
        else:
            logger.warning(f"Falla en verificación local: {exc}")
        return None
    except Exception as exc:
        logger.error(f"Error inesperado decodificando local: {exc}")
        return None
