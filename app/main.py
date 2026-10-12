"""Punto de entrada principal de GeoMaps Backend (FastAPI).
Configura ciclo de vida, middleware CORS, excepciones y registro de rutas.
"""

import logging
import json
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Registro global de modelos de ML para acceso desde servicios (Reservado para futuro)
ml_models = {}

# Importación de Rutas Seguras
from app.api.v1 import (
    auth_routes, layer_routes, 
    download_routes, search_routes, api_keys, ogc_routes, cartografia_routes, support as support_routes
)
from app.api.v1.admin import router as admin_router

from app.core.config import settings
from app.core.exceptions import setup_exception_handlers
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja eventos de encendido y apagado de la aplicación."""
    logger.info("Arrancando GeoMaps.")
    # El motor YOLO ha sido deshabilitado temporalmente para optimizar recursos
    yield
    # Limpieza
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


# Registro compartido de trazas y finalización de cuotas.
from app.api.middleware import APIKeyUsageMiddleware

app.add_middleware(APIKeyUsageMiddleware)


setup_exception_handlers(app)

# ── RUTAS ─────────────────────────────────────────────────────────────────────
app.include_router(auth_routes.router, prefix=settings.API_V1_STR)
app.include_router(layer_routes.router, prefix=f"{settings.API_V1_STR}/layers")
app.include_router(download_routes.router, prefix=f"{settings.API_V1_STR}/resources")
app.include_router(search_routes.router, prefix=f"{settings.API_V1_STR}/search")
app.include_router(cartografia_routes.router, prefix=f"{settings.API_V1_STR}/cartografia", tags=["Cartografia"])
app.include_router(support_routes.router, prefix=f"{settings.API_V1_STR}/support", tags=["Support"])
app.include_router(ogc_routes.router, prefix=f"{settings.API_V1_STR}/ogc", tags=["OGC"])
app.include_router(admin_router, prefix=settings.API_V1_STR)
app.include_router(api_keys.router, prefix=f"{settings.API_V1_STR}/keys", tags=["API Keys"])

# Rutas de IA
from app.api.v1.endpoints import ia_router
app.include_router(ia_router.router, prefix=f"{settings.API_V1_STR}/ia", tags=["Artificial Intelligence"])

# Rutas de Reportes IA
from app.api.v1.endpoints import report_router
app.include_router(report_router.router, prefix=f"{settings.API_V1_STR}/reports", tags=["Reports"])


@app.get("/health")
async def health_check():
    """Diagnóstico rápido del estado del servicio."""
    return {"status": "ok", "version": "2.0.0"}
