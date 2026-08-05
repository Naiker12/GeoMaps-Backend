"""Punto de entrada principal de GeoMaps Backend (FastAPI).
Configura ciclo de vida, middleware CORS, excepciones y registro de rutas organizadas por slices verticales Geo-*.
"""

import logging
import time
import json
import asyncio
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# Registro global de modelos de ML
ml_models = {}

# Importación de Rutas por Slices Verticales Geo-*
from app.Geo_Auth.router import router as auth_router
from app.Geo_Proyectos.router import router as project_router
from app.Geo_Capas.router import router as layer_router
from app.Geo_Descargas.router import router as download_router
from app.Geo_Busqueda.router import router as search_router
from app.Geo_Cartografia.router import router as cartografia_router
from app.Geo_Soporte.router import router as support_router
from app.Geo_OGC.router import router as ogc_router
from app.Geo_ApiKeys.router import router as api_keys_router
from app.Geo_IA.router import router as ia_router
from app.Geo_Reportes.router import router as report_router

from app.shared.core.config import settings
from app.shared.core.exceptions import setup_exception_handlers
from app.shared.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja eventos de encendido y apagado de la aplicación."""
    logger.info("Arrancando GeoMaps.")
    yield
    ml_models.clear()
    logger.info("GeoMaps apagado.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
def _origin_items(value: Any) -> list[str]:
    """Normaliza variables CORS: lista JSON, lista Python o valores con comas."""
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip().rstrip("/") for item in value if str(item).strip()]
    raw_value = str(value).strip()
    if raw_value.startswith("["):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = raw_value
        if isinstance(parsed, list):
            return _origin_items(parsed)
    return [item.strip().rstrip("/") for item in raw_value.split(",") if item.strip()]


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

ALLOWED_ORIGINS = sorted(
    set(
        ALLOWED_ORIGINS
        + _origin_items(getattr(settings, "BACKEND_CORS_ORIGINS", None))
        + _origin_items(getattr(settings, "FRONTEND_URL", None))
    )
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time", "X-Generated-By", "Content-Disposition"],
)


# ── MIDDLEWARE DE LOGGING ─────────────────────────────────────────────────────
@app.middleware("http")
async def combined_trace_and_log_middleware(request: Request, call_next):
    """Intercepta peticiones para medir tiempo y registrar logs de API Keys."""
    if request.method == "OPTIONS":
        return await call_next(request)

    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)

    endpoint = request.url.path
    if not endpoint.startswith(settings.API_V1_STR):
        return response

    raw_api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not raw_api_key:
        return response

    if response.status_code == 429:
        return response

    api_key_id = getattr(request.state, "api_key_id", None)
    user_id = getattr(request.state, "user_id", None)
    api_key_hint = None
    if not api_key_id and raw_api_key and len(raw_api_key) > 4:
        api_key_hint = raw_api_key[-4:]

    async def log_task():
        try:
            from app.shared.db.session import get_db
            from app.Geo_ApiKeys.service import APIKeyService
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
                break
        except Exception as e:
            logger.warning(f"log_task falló silenciosamente: {e}")

    asyncio.create_task(log_task())
    return response


setup_exception_handlers(app)

# ── RUTAS ─────────────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(project_router, prefix=f"{settings.API_V1_STR}/projects")
app.include_router(layer_router, prefix=f"{settings.API_V1_STR}/layers")
app.include_router(download_router, prefix=f"{settings.API_V1_STR}/resources")
app.include_router(search_router, prefix=f"{settings.API_V1_STR}/search")
app.include_router(cartografia_router, prefix=f"{settings.API_V1_STR}/cartografia", tags=["Cartografia"])
app.include_router(support_router, prefix=f"{settings.API_V1_STR}/support", tags=["Support"])
app.include_router(ogc_router, prefix=f"{settings.API_V1_STR}/ogc", tags=["OGC"])
app.include_router(api_keys_router, prefix=f"{settings.API_V1_STR}/keys", tags=["API Keys"])
app.include_router(ia_router, prefix=f"{settings.API_V1_STR}/ia", tags=["Artificial Intelligence"])
app.include_router(report_router, prefix=f"{settings.API_V1_STR}/reports", tags=["Reports"])


@app.get("/health")
async def health_check():
    """Diagnóstico rápido del estado del servicio."""
    return {"status": "ok", "version": "2.0.0"}
