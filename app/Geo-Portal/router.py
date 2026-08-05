from fastapi import APIRouter

# Router principal para la Aplicación Pública (Geoportal)
# Estas rutas son públicas por defecto a menos que se especifique lo contrario en el endpoint
router = APIRouter(
    prefix="/portal",
    tags=["portal"]
)

@router.get("/config")
async def get_public_config():
    """Ejemplo de endpoint público para el portal."""
    return {
        "app_name": "GeoMaps Portal",
        "public_access": True
    }

# Aquí se incluirán routers de capas públicas, mapas, etc.
# router.include_router(public_layers_router)
