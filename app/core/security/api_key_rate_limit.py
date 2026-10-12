"""Límite por API key compartido entre procesos mediante Redis."""

import logging
import uuid

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Una ventana de 60 segundos comienza con la primera petición admitida.
# El script cuenta y expira en una única operación; rechazar no extiende la ventana.
RATE_LIMIT_SCRIPT = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
local ttl = redis.call('TTL', KEYS[1])
if count >= tonumber(ARGV[1]) then
    if ttl < 0 then
        redis.call('EXPIRE', KEYS[1], 60)
        ttl = 60
    end
    return {0, math.max(ttl, 1)}
end
redis.call('INCR', KEYS[1])
if ttl < 0 then
    redis.call('EXPIRE', KEYS[1], 60)
end
return {1, 0}
"""


async def enforce_api_key_rate_limit(key_id: uuid.UUID, rpm: int | None) -> None:
    """None conserva llaves sin límite RPM; cada petición admitida consume uno."""
    if rpm is None:
        return
    if rpm <= 0:
        raise HTTPException(503, detail="Configuración de límite de API Key inválida")

    try:
        async with Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        ) as client:
            allowed, retry_after = await client.eval(
                RATE_LIMIT_SCRIPT, 1, f"geomaps:api-key:rpm:{key_id}", rpm
            )
    except RedisError as exc:
        logger.error("No se pudo comprobar el límite RPM de la API key %s", key_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de límites de API Key no está disponible",
            headers={"Retry-After": "5"},
        ) from exc

    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Límite de peticiones por minuto alcanzado para esta API Key.",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )
