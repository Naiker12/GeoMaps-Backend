from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.exceptions import MIDASException, midas_exception_handler, global_exception_handler
from app.core.logging import setup_logging
from app.api.v1 import auth as auth_v1
from app.api.v1 import admin as admin_v1
from app.api.v1 import portal as portal_v1
from app.api.routes import project_routes as old_project_routes

# Inicializar logging
setup_logging()

app = FastAPI(
    title="MIDAS - DEBUGGING REFRESH - 12345",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="Backend profesional para el sistema MIDAS – Gestión de Proyectos Inmobiliarios"
)

# Configuración de CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Por defecto para desarrollo
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Manejadores de Excepciones
app.add_exception_handler(MIDASException, midas_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Rutas de Autenticación de v1 (Supabase Sync)
app.include_router(auth_v1.router, prefix=f"{settings.API_V1_STR}")

# Rutas de Admin y Portal de v1
app.include_router(admin_v1.router, prefix=f"{settings.API_V1_STR}")
app.include_router(portal_v1.router, prefix=f"{settings.API_V1_STR}")

# Mantener project_routes por ahora si no están migrados a v1
app.include_router(old_project_routes.router, prefix=f"{settings.API_V1_STR}/projects", tags=["projects"])

@app.get("/")
async def root():
    return {
        "message": "Bienvenido a la API de MIDAS",
        "version": "1.0.0",
        "status": "online"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
