from fastapi import APIRouter, Depends
from app.core.security.dependencies import require_admin
from app.api.v1.users import router as users_router
from .analytics import router as analytics_router
from .api_keys import router as api_keys_router
from .ia_monitoring import router as ia_monitoring_router

# Router principal para el Panel de Administración
# Todas las rutas bajo este router requerirán rol de admin o super_admin
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)]
)

# Incluir submódulos de administración
router.include_router(users_router)
router.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
router.include_router(api_keys_router, prefix="/api-keys", tags=["api-keys"])
router.include_router(ia_monitoring_router, prefix="/ia", tags=["admin-ia"])
