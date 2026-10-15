from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import BaseModel, SecretStr, Field, ConfigDict
from app.core.config import settings

PROVIDERS = [
    dict(id='google', name='Google Gemini', base_url='https://generativelanguage.googleapis.com/v1beta', protocol='google', requires_key=True),
    dict(id='openai', name='OpenAI', base_url='https://api.openai.com/v1', protocol='openai', requires_key=True),
    dict(id='anthropic', name='Anthropic', base_url='https://api.anthropic.com/v1', protocol='anthropic', requires_key=True),
    dict(id='mistral', name='Mistral AI', base_url='https://api.mistral.ai/v1', protocol='openai', requires_key=True),
    dict(id='groq', name='Groq', base_url='https://api.groq.com/openai/v1', protocol='openai', requires_key=True),
    dict(id='openrouter', name='OpenRouter', base_url='https://openrouter.ai/api/v1', protocol='openai', requires_key=True),
    dict(id='ollama', name='Ollama (local)', base_url='http://localhost:11434/v1', protocol='openai', requires_key=False),
    dict(id='lmstudio', name='LM Studio (local)', base_url='http://localhost:1234/v1', protocol='openai', requires_key=False),
    dict(id='custom', name='Compatible con OpenAI', base_url='', protocol='openai', requires_key=False),
]

class ConnectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    provider: str
    base_url: str
    api_key: SecretStr = SecretStr('')

class ConnectModelRequest(ConnectionRequest):
    model_id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    is_default: bool = False


def cipher() -> Fernet:
    key = settings.AI_PROVIDER_ENCRYPTION_KEY
    if not key:
        raise HTTPException(503, 'Configura AI_PROVIDER_ENCRYPTION_KEY en el servidor antes de guardar una API key.')
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, 'La clave de cifrado del servidor no es válida.') from None


def encrypt_key(key: str) -> str | None:
    return cipher().encrypt(key.encode()).decode() if key else None


def decrypt_key(value: str | None) -> str:
    if not value:
        return ''
    try:
        return cipher().decrypt(value.encode()).decode()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'No se pudo descifrar la credencial del proveedor.') from None


def provider_info(provider: str) -> dict:
    info = next((p for p in PROVIDERS if p['id'] == provider), None)
    if not info:
        raise HTTPException(422, 'Proveedor no compatible.')
    return info


def validate_url(provider: str, value: str) -> str:
    info = provider_info(provider)
    value = value.strip().rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(422, 'Usa una URL HTTP/HTTPS sin credenciales, parámetros ni fragmentos.')
    if provider not in ('ollama', 'lmstudio', 'custom') and value != info['base_url']:
        raise HTTPException(422, 'Este proveedor debe usar su URL oficial.')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
        for entry in addresses:
            address = ipaddress.ip_address(entry[4][0])
            if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
                raise HTTPException(422, 'La dirección de destino no está permitida.')
            if parsed.scheme == 'http' and not (address.is_private or address.is_loopback):
                raise HTTPException(422, 'Las conexiones remotas requieren HTTPS.')
    except (socket.gaierror, ValueError):
        raise HTTPException(422, 'No se pudo resolver la URL del proveedor.') from None
    return value


def reported_capabilities(item):
    parameters = item.get('supported_parameters')
    architecture = item.get('architecture') or {}
    context = item.get('context_length') or item.get('inputTokenLimit')
    return {
        'has_function_calling': ('tools' in parameters) if isinstance(parameters, list) else None,
        'has_vision': ('image' in architecture.get('input_modalities', [])) if 'input_modalities' in architecture else None,
        'max_context_tokens': context if isinstance(context, int) and 1024 <= context <= 2000000 else None,
        'supported_parameters': parameters if isinstance(parameters, list) else [],
        'capability_source': 'provider_catalog' if parameters is not None else 'not_reported',
    }


async def discover_models(connection: ConnectionRequest) -> list[dict]:
    info = provider_info(connection.provider)
    base_url = validate_url(connection.provider, connection.base_url)
    key = connection.api_key.get_secret_value().strip()
    if info['requires_key'] and not key:
        raise HTTPException(422, 'Este proveedor requiere una API key.')
    headers = {}
    if info['protocol'] == 'google':
        headers['x-goog-api-key'] = key
    elif info['protocol'] == 'anthropic':
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
    elif key:
        headers['Authorization'] = 'Bearer ' + key
    models = []
    params = {}
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
        for _ in range(20):
            try:
                response = await client.get(base_url + '/models', headers=headers, params=params)
                if response.status_code in (401, 403):
                    raise HTTPException(400, 'La credencial fue rechazada por el proveedor.')
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                raise HTTPException(502, 'No se pudieron cargar los modelos del proveedor. Revisa su URL y disponibilidad.') from None
            for item in payload.get('models' if info['protocol'] == 'google' else 'data', []):
                if info['protocol'] == 'google' and 'generateContent' not in item.get('supportedGenerationMethods', []):
                    continue
                model_id = str(item.get('id') or item.get('name') or '').removeprefix('models/')
                if model_id:
                    models.append({**reported_capabilities(item), 'id': model_id, 'name': item.get('displayName') or item.get('display_name') or (item.get('name') if info['protocol'] != 'google' else None) or model_id})
            if info['protocol'] == 'google' and payload.get('nextPageToken'):
                params = {'pageToken': payload['nextPageToken']}
            elif info['protocol'] == 'anthropic' and payload.get('has_more'):
                params = {'after_id': payload['last_id']}
            else:
                return sorted({m['id']: m for m in models}.values(), key=lambda m: m['name'].lower())
    raise HTTPException(502, 'El catálogo excede el límite de paginación. No se guardaron resultados incompletos.')
