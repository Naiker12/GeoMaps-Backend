from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.exceptions import MIDASException, midas_exception_handler, global_exception_handler
from app.core.logging import setup_logging
from app.api.v1 import auth as auth_v1
from app.api.v1 import admin as admin_v1
from app.api.v1 import portal as portal_v1
from app.api.v1 import layers as layers_v1
from app.api.v1 import search as search_v1
from app.api.routes import project_routes as old_project_routes

# Inicializar logging
setup_logging()

app = FastAPI(
    title="GEOMAPS - DEBUGGING REFRESH - 12345",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="Backend profesional para el sistema MIDAS – Gestión de Proyectos Inmobiliarios"
)

# Configuración de CORS
raw_origins = [str(origin).rstrip("/") for origin in settings.BACKEND_CORS_ORIGINS] if settings.BACKEND_CORS_ORIGINS else []
if settings.FRONTEND_URL:
    raw_origins.append(settings.FRONTEND_URL.rstrip("/"))

# Filtrar "*" ya que es incompatible con allow_credentials=True
origins = [o for o in raw_origins if o != "*"]
if not origins:
    # Fallback de seguridad para desarrollo
    origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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

# Rutas de Capas
app.include_router(layers_v1.router, prefix=f"{settings.API_V1_STR}/layers", tags=["layers"])

# Rutas de Búsqueda
app.include_router(search_v1.router, prefix=f"{settings.API_V1_STR}/search", tags=["search"])

# Mantener project_routes por ahora si no están migrados a v1
app.include_router(old_project_routes.router, prefix=f"{settings.API_V1_STR}/projects", tags=["projects"])

@app.get("/")
async def root():
    return {
        "message": "Bienvenido a la API de MIDAS",
        "version": "1.0.0",
        "status": "online",
        "debug": "CORS_FIXED_V3"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
