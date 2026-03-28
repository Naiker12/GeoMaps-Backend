"""Punto de entrada principal de GeoMaps Backend (FastAPI).
Configura ciclo de vida, middleware CORS, excepciones y registro de rutas.
"""

import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# Importación de Rutas Seguras
from app.api.v1 import (
    auth_routes, layer_routes, 
    download_routes, search_routes, api_keys
)
from app.api.v1.admin import router as admin_router
from app.api.routes import project_routes

from app.core.config import settings
from app.core.exceptions import setup_exception_handlers
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja eventos de encendido y apagado de la aplicación."""
    logger.info("Arrancando GeoMaps.")
    yield
    logger.info("Apagando GeoMaps Engine.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# CORRECCIÓN: allow_origins explícitos + allow_credentials=True son mutuamente
# excluyentes con "*". Se usa lista explícita para desarrollo y producción.
ALLOWED_ORIGINS = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",   # Vite
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]

if getattr(settings, "BACKEND_CORS_ORIGINS", None):
    extra = [str(o).rstrip("/") for o in settings.BACKEND_CORS_ORIGINS]
    ALLOWED_ORIGINS = list(set(ALLOWED_ORIGINS + extra))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time"],
)


# ── MIDDLEWARE DE LOGGING ─────────────────────────────────────────────────────
@app.middleware("http")
async def combined_trace_and_log_middleware(request: Request, call_next):
    """Intercepta peticiones para medir tiempo y registrar logs de API Keys."""
    # Saltar OPTIONS (pre-flight CORS) inmediatamente
    if request.method == "OPTIONS":
        return await call_next(request)

    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)

    endpoint = request.url.path
    # Solo loggear rutas de la API
    if not endpoint.startswith(settings.API_V1_STR):
        return response

    # Detectar si la petición lleva una API Key
    raw_api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    
    # Solo loggear si hay una API Key involucrada (no logeamos peticiones JWT/anónimas)
    if not raw_api_key:
        return response

    # NO loggear respuestas 429 (rate limit) — el rechazo NO debe contar como uso
    if response.status_code == 429:
        return response

    # Usar getattr para evitar fallos si request.state no tiene los atributos
    api_key_id = getattr(request.state, "api_key_id", None)
    user_id = getattr(request.state, "user_id", None)

    # Capturar hint de la key si la auth falló
    api_key_hint = None
    if not api_key_id and raw_api_key and len(raw_api_key) > 4:
        api_key_hint = raw_api_key[-4:]

    # Ejecutar logging en segundo plano para no bloquear el ciclo de request
    import asyncio

    async def log_task():
        try:
            from app.db.session import get_db
            from app.services.api_key_service import APIKeyService

            async for db in get_db():
                service = APIKeyService(db)
                if api_key_id and user_id:
                    await service.log_api_usage(
                        api_key_id=api_key_id,
                        user_id=user_id,
                        endpoint=endpoint,
                        method=request.method,
                        status_code=response.status_code,
                        response_time_ms=int(process_time * 1000),
                        tokens_used=1,
                        ip_address=request.client.host if request.client else None,
                        user_agent=request.headers.get("user-agent"),
                    )
                else:
                    await service.log_failed_attempt(
                        endpoint=endpoint,
                        method=request.method,
                        status_code=response.status_code,
                        response_time_ms=int(process_time * 1000),
                        ip_address=request.client.host if request.client else None,
                        user_agent=request.headers.get("user-agent"),
                        api_key_hint=api_key_hint,
                    )
                break  # solo una iteración
        except Exception as e:
            logger.warning(f"log_task falló silenciosamente: {e}")

    asyncio.create_task(log_task())

    return response


setup_exception_handlers(app)

# ── RUTAS ─────────────────────────────────────────────────────────────────────
app.include_router(auth_routes.router, prefix=settings.API_V1_STR)
app.include_router(project_routes.router, prefix=f"{settings.API_V1_STR}/projects")
app.include_router(layer_routes.router, prefix=f"{settings.API_V1_STR}/layers")
app.include_router(download_routes.router, prefix=f"{settings.API_V1_STR}/resources")
app.include_router(search_routes.router, prefix=f"{settings.API_V1_STR}/search")
app.include_router(admin_router, prefix=settings.API_V1_STR)
app.include_router(api_keys.router, prefix=f"{settings.API_V1_STR}/keys", tags=["API Keys"])


@app.get("/health")
async def health_check():
    """Diagnóstico rápido del estado del servicio."""
    return {"status": "ok", "version": "2.0.0"}