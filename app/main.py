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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin).rstrip("/") for origin in settings.BACKEND_CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def combined_trace_and_log_middleware(request: Request, call_next):
    """Intercepta peticiones para medir tiempo y registrar logs de API Keys asíncronamente."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    
    # ── LOGGING DE API KEY ──
    # Si la petición fue autenticada con API Key, get_user_from_api_key inyecta estos en request.state
    if hasattr(request.state, "api_key_id") and hasattr(request.state, "user_id"):
        from app.db.session import SessionLocal
        from app.services.api_key_service import APIKeyService
        import asyncio
        
        async def log_task(api_key_id, user_id, status_code, process_time_ms, endpoint, method, ip_address, user_agent):
            async with SessionLocal() as db:
                service = APIKeyService(db)
                await service.log_api_usage(
                    api_key_id=api_key_id,
                    user_id=user_id,
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    response_time_ms=process_time_ms,
                    tokens_used=1, # Default 1 token
                    ip_address=ip_address,
                    user_agent=user_agent
                )
        
        # Ejecutar en segundo plano para no bloquear el request cycle
        asyncio.create_task(
            log_task(
                request.state.api_key_id,
                request.state.user_id,
                response.status_code,
                int(process_time * 1000),
                request.url.path,
                request.method,
                request.client.host if request.client else None,
                request.headers.get("user-agent")
            )
        )
        
    return response


setup_exception_handlers(app)

# Registro de Rutas
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