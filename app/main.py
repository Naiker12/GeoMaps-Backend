from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import traceback

# Configuración de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.core.config import settings
from app.api.v1 import auth as auth_v1
from app.api.v1.admin import router as admin_router
from app.api.v1.portal import router as portal_router

app = FastAPI(
    title="GeoMaps API",
    description="Backend para gestión de datos geoespaciales con FastAPI y Supabase Auth",
    version="1.0.0"
)

# --- MANEJO GLOBAL DE ERRORES ---

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "detail": exc.detail,
            "error_code": "HTTP_ERROR"
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {str(exc)}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Ha ocurrido un error interno en el servidor.",
            "detail": "Error interno del servidor",
            "error_code": "INTERNAL_SERVER_ERROR"
        },
    )

# --- API ROUTERS (Multi-Tier Architecture) ---

# TIER 1: Autenticación & Seguridad (Público/Compartido)
app.include_router(auth_v1.router, prefix="/api/v1")

# TIER 2: Portal Público (Geoportal)
app.include_router(portal_router, prefix="/api/v1")

# TIER 3: Panel Administrativo (Admin)
app.include_router(admin_router, prefix="/api/v1")

# --- MIDDLEWARE & CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ENDPOINTS DE SISTEMA ---

@app.get("/api/health")
async def health_check():
    """Endpoint para monitoreo de salud del servicio."""
    return {
        "status": "healthy", 
        "service": "GeoMaps API",
        "version": "1.0.0"
    }

@app.get("/")
async def root():
    """Punto de entrada informativo de la API."""
    return {
        "app": "GeoMaps Intelligence API",
        "environment": "production" if not settings.FRONTEND_URL.startswith("http://localhost") else "development",
        "endpoints": {
            "auth": "/api/v1/auth",
            "admin": "/api/v1/admin",
            "portal": "/api/v1/portal",
            "docs": "/docs"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
