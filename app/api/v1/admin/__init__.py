from fastapi import APIRouter, Depends
from app.core.security.dependencies import require_admin
from app.api.v1.users import router as users_router
from app.api.v1.admin.analytics import router as analytics_router

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
