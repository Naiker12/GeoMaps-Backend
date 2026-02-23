"""
Script de diagnóstico para verificar que el SUPABASE_JWT_SECRET puede decodificar
tokens de Supabase correctamente.

Uso:
    cd GeoMaps-Backend
    python debug_jwt.py <token_de_supabase>

Para obtener el token: Abre la consola del navegador después de login con Google
y ejecuta: (await supabase.auth.getSession()).data.session.access_token
"""
import sys
import os
import base64
import binascii

# Cargar variables de entorno
from dotenv import load_dotenv
load_dotenv()

secret = os.getenv("SUPABASE_JWT_SECRET", "")
print(f"\n=== DIAGNÓSTICO JWT ===")
print(f"Secret (primeros 20 chars): {secret[:20]}...")
print(f"Longitud del secret: {len(secret)}")
print(f"Contiene '+': {'SÍ' if '+' in secret else 'NO'}")
print(f"Contiene '/': {'SÍ' if '/' in secret else 'NO'}")
print(f"Termina con '=': {'SÍ' if secret.endswith('=') else 'NO'}")

if len(sys.argv) < 2:
    print("\n❌ Por favor proporciona el token como argumento:")
    print("   python debug_jwt.py <token>")
    sys.exit(1)

token = sys.argv[1]
print(f"\nToken (primeros 50 chars): {token[:50]}...")

from jose import jwt as jose_jwt, JWTError

print("\n--- Intento 1: Secret como string literal ---")
try:
    payload = jose_jwt.decode(
        token, secret, algorithms=["HS256"],
        options={"verify_aud": False, "verify_iat": False, "verify_exp": True}
    )
    print(f"✅ ÉXITO - sub={payload.get('sub')}, email={payload.get('email')}")
except JWTError as e:
    print(f"❌ FALLÓ: {e}")

print("\n--- Intento 2: Secret decodificado como base64 estándar ---")
try:
    # Añadir padding si es necesario
    padded = secret + "=" * (4 - len(secret) % 4)
    decoded = base64.b64decode(padded)
    print(f"  Secret decodificado: {len(decoded)} bytes")
    payload = jose_jwt.decode(
        token, decoded, algorithms=["HS256"],
        options={"verify_aud": False, "verify_iat": False, "verify_exp": True}
    )
    print(f"✅ ÉXITO - sub={payload.get('sub')}, email={payload.get('email')}")
except (binascii.Error, ValueError, JWTError) as e:
    print(f"❌ FALLÓ: {e}")

print("\n--- Intento 3: Secret como base64 URL-safe ---")
try:
    url_safe = secret.replace('+', '-').replace('/', '_').rstrip('=')
    decoded = base64.urlsafe_b64decode(url_safe + "==")
    print(f"  Secret decodificado: {len(decoded)} bytes")
    payload = jose_jwt.decode(
        token, decoded, algorithms=["HS256"],
        options={"verify_aud": False, "verify_iat": False, "verify_exp": True}
    )
    print(f"✅ ÉXITO - sub={payload.get('sub')}, email={payload.get('email')}")
except (binascii.Error, ValueError, JWTError) as e:
    print(f"❌ FALLÓ: {e}")

print("\n--- Info del token (sin verificar firma) ---")
try:
    import json
    parts = token.split('.')
    if len(parts) >= 2:
        header_raw = parts[0] + "=" * (4 - len(parts[0]) % 4)
        payload_raw = parts[1] + "=" * (4 - len(parts[1]) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_raw))
        payload_unverified = json.loads(base64.urlsafe_b64decode(payload_raw))
        print(f"  Header: {header}")
        print(f"  Algorithm: {header.get('alg')}")
        print(f"  sub: {payload_unverified.get('sub')}")
        print(f"  email: {payload_unverified.get('email')}")
        import datetime
        exp = payload_unverified.get('exp', 0)
        exp_dt = datetime.datetime.fromtimestamp(exp, tz=datetime.timezone.utc)
        print(f"  Expira: {exp_dt} ({'EXPIRADO' if exp_dt < datetime.datetime.now(datetime.timezone.utc) else 'VÁLIDO'})")
        print(f"  iss: {payload_unverified.get('iss')}")
except Exception as e:
    print(f"  Error al decodificar payload: {e}")
