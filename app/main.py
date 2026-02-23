from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
import logging
import traceback

# Configuración de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.core.security.dependencies import get_current_user, get_current_admin
from app.domain.models.user import User
from app.core.config import settings
from app.api.v1 import users, auth

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

# API Routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "GeoMaps API Online", "docs": "/docs"}

# --- ENDPOINTS PROTEGIDOS ---


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
