"""Trazas y finalización de consumo de API keys antes de retornar la respuesta."""

import asyncio
import logging
import time

from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.api_keys import APIKeyService

logger = logging.getLogger(__name__)
USAGE_LOG_TIMEOUT_SECONDS = 5


async def _record_usage(request: Request, status_code: int, elapsed: float) -> None:
    raw_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not raw_key or not request.url.path.startswith(settings.API_V1_STR):
        return
    reservation_id = getattr(request.state, "api_key_quota_reservation_id", None)
    if status_code == 429 and reservation_id is None:
        return
    key_id = getattr(request.state, "api_key_id", None)
    user_id = getattr(request.state, "user_id", None)
    common = {
        "endpoint": request.url.path, "method": request.method,
        "status_code": status_code, "response_time_ms": int(elapsed * 1000),
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
    try:
        async with asyncio.timeout(USAGE_LOG_TIMEOUT_SECONDS):
            async with SessionLocal() as db:
                service = APIKeyService(db)
                if key_id and user_id:
                    await service.log_api_usage(
                        **common, api_key_id=key_id, user_id=user_id,
                        tokens_used=1, reservation_id=reservation_id,
                    )
                else:
                    await service.log_failed_attempt(
                        **common, api_key_hint=raw_key[-4:] if len(raw_key) > 4 else None,
                    )
    except Exception:
        # La respuesta del caso de uso se conserva. Una reserva no finalizada
        # continúa contando durante 24 horas, sin abrir cupo por fallo de logging.
        logger.exception("No se pudo finalizar el registro de uso de API Key")


class APIKeyUsageMiddleware:
    """Middleware ASGI: conserva streaming sin introducir streams intermedios."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        start = time.perf_counter()
        response_started = False

        async def send_with_usage(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                elapsed = time.perf_counter() - start
                await _record_usage(request, message["status"], elapsed)
                MutableHeaders(scope=message)["X-Process-Time"] = str(elapsed)
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_usage)
        except Exception:
            if not response_started:
                await _record_usage(request, 500, time.perf_counter() - start)
            raise
