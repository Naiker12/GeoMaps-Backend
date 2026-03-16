import logging
import base64
import binascii
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from app.core.config import settings

logger = logging.getLogger(__name__)

def create_access_token(data: Any, expires_delta: Optional[timedelta] = None) -> str:
    """Crea un token de acceso propio firmado con el secret de Supabase, compatible con la validación local."""
    if isinstance(data, dict):
        to_encode = data.copy()
    else:
        to_encode = {"sub": str(data)}
        
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL}/auth/v1"
    })
    
    secret_raw = settings.SUPABASE_JWT_SECRET
    try:
        secret_stripped = secret_raw.strip()
        missing_padding = len(secret_stripped) % 4
        if missing_padding:
            secret_stripped += "=" * (4 - missing_padding)
        secret_bytes = base64.b64decode(secret_stripped)
        return jwt.encode(to_encode, secret_bytes, algorithm="HS256")
    except Exception:
        return jwt.encode(to_encode, secret_raw, algorithm="HS256")

def create_refresh_token(subject: Any) -> str:
    """Crea un token de refresco con una duración mayor."""
    return create_access_token(subject, expires_delta=timedelta(days=7))

# Cache para las llaves JWKS de Supabase
_jwks_cache: Dict[str, Any] = {}
_jwks_last_fetch: Optional[datetime] = None
JWKS_CACHE_TTL = timedelta(hours=24)

def fetch_supabase_jwks() -> Optional[Dict[str, Any]]:
    """
    Obtiene las llaves públicas (JWKS) del servidor de Supabase.
    """
    global _jwks_cache, _jwks_last_fetch
    
    now = datetime.now()
    if _jwks_last_fetch and (now - _jwks_last_fetch) < JWKS_CACHE_TTL:
        return _jwks_cache

    jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    try:
        logger.info(f"Cargando JWKS desde {jwks_url}")
        with httpx.Client(timeout=10) as client:
            response = client.get(jwks_url)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_last_fetch = now
            return _jwks_cache
    except Exception as e:
        logger.error(f"Error al obtener JWKS de Supabase: {e}")
        return None

def decode_supabase_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decodifica un token JWT de Supabase soportando tanto HS256 como ES256 (JWKS).
    """
    if not token:
        return None

    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.get_unverified_claims(token)
        alg = header.get("alg")
        kid = header.get("kid")
        expected_issuer = f"{settings.SUPABASE_URL}/auth/v1"
    except Exception as e:
        logger.error(f"Error al leer estructura básica del token: {e}")
        return None

    decode_options = {
        "verify_aud": True,
        "verify_iat": False,
        "verify_exp": True,
        "verify_iss": True
    }

    # --- Caso 1: ES256 (Asimétrico - Llave Pública vía JWKS) ---
    if alg == "ES256":
        jwks = fetch_supabase_jwks()
        if jwks:
            try:
                # El token ES256 se valida contra las llaves públicas de Supabase
                # python-jose puede manejar objetos JWKS directamente o buscar por kid
                return jwt.decode(
                    token,
                    jwks,
                    algorithms=["ES256"],
                    options=decode_options,
                    audience="authenticated",
                    issuer=expected_issuer
                )
            except JWTError as e:
                logger.error(f"Fallo al validar token ES256: {e}")
        else:
            logger.error("No se pudo obtener el JWKS para validar el token ES256")

    # --- Caso 2: HS256 (Simétrico - Secret Compartido) ---
    elif alg == "HS256":
        secret_raw = settings.SUPABASE_JWT_SECRET
        
        # Intentar con Secret decodificado de Base64
        try:
            secret_stripped = secret_raw.strip()
            missing_padding = len(secret_stripped) % 4
            if missing_padding:
                secret_stripped += "=" * (4 - missing_padding)
            secret_bytes = base64.b64decode(secret_stripped)
            
            return jwt.decode(
                token,
                secret_bytes,
                algorithms=["HS256"],
                options=decode_options,
                audience="authenticated",
                issuer=expected_issuer
            )
        except (binascii.Error, ValueError, JWTError) as e:
            logger.warning(f"Fallo validación HS256 con secret Base64: {e}")

        # Fallback para HS256 sin Base64
        try:
            return jwt.decode(
                token,
                secret_raw,
                algorithms=["HS256"],
                options=decode_options,
                audience="authenticated",
                issuer=expected_issuer
            )
        except JWTError as e:
            logger.error(f"Fallo definitivo HS256: {e}")
    
    else:
        logger.error(f"Algoritmo {alg} no soportado o bloqueado por seguridad.")

    return None
