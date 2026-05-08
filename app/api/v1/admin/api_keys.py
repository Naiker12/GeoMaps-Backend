import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin_user, get_db
from app.db.models.user import User
from app.schemas.api_key import (
    APIKeyAdminResponse,
    APIKeyCreate,
    APIKeyStatsOverview,
    PaginatedAPIKeyAdminResponse,
)
from app.services.api_key_service import APIKeyService

router = APIRouter()


@router.get("/", response_model=PaginatedAPIKeyAdminResponse)
async def list_admin_api_keys(
    status: Optional[str] = None,
    role: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
    # Solo admin puede acceder (asegurado por el router padre en admin/__init__.py)
):
    """Lista de todas las API Keys globales con filtros para administración."""
    api_key_service = APIKeyService(db)
    keys, total = await api_key_service.list_admin_keys_paginated(
        status=status, role=role, user_id=user_id, search=search, page=page, limit=limit
    )
    return {"items": keys, "total": total, "page": page, "limit": limit}


@router.post(
    "/", response_model=APIKeyAdminResponse, status_code=status.HTTP_201_CREATED
)
async def admin_create_api_key(
    api_key_in: APIKeyCreate,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Genera una nueva API Key para un usuario específico desde el panel administrativo."""
    if not api_key_in.user_id:
        raise HTTPException(
            status_code=400, detail="Debe proporcionar un user_id para asignar la key."
        )

    api_key_service = APIKeyService(db)
    api_key, raw_key = await api_key_service.create_api_key(
        user_id=current_admin.id,  # el admin es quien ejecuta
        api_key_in=api_key_in,
        assigned_user_id=api_key_in.user_id,
    )

    response = APIKeyAdminResponse.model_validate(api_key)
    response.key = raw_key
    return response


@router.patch("/{key_id}/revoke", response_model=APIKeyAdminResponse)
async def admin_revoke_api_key(
    key_id: uuid.UUID,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoca una API Key global de cualquier usuario."""
    api_key_service = APIKeyService(db)
    revoked = await api_key_service.revoke_api_key(
        key_id=key_id, user_id=current_admin.id, is_admin=True
    )
    if not revoked:
        raise HTTPException(status_code=404, detail="API Key no encontrada.")
    return revoked


@router.get("/stats/overview", response_model=APIKeyStatsOverview)
async def get_admin_stats_overview(
    db: AsyncSession = Depends(get_db),
):
    """Obtiene el resumen global de métricas del sistema de API Keys."""
    api_key_service = APIKeyService(db)
    return await api_key_service.get_overview_stats()


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
):
    """Elimina permanentemente cualquier API Key (Solo ADMIN)."""
    api_key_service = APIKeyService(db)
    success = await api_key_service.delete_api_key(
        key_id, current_admin.id, is_admin=True
    )
    if not success:
        raise HTTPException(status_code=404, detail="API Key no encontrada.")
    return None


# --- Configuración Avanzada ---


@router.patch("/settings/rate-limit")
async def update_global_rate_limit(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
):
    """Actualiza el límite de RPM global o por defecto (Solo ADMIN)."""
    rpm = data.get("rpm_limit")
    if not rpm:
        raise HTTPException(status_code=400, detail="Se requiere rpm_limit")

    api_key_service = APIKeyService(db)
    result = await api_key_service.update_global_rate_limit(rpm, current_admin.id)
    return {"status": "success", "rpm_limit": result.rpm_limit}


@router.post("/settings/pause")
async def toggle_traffic_pause(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
):
    """Pausa o reanuda el tráfico global de la API (Solo ADMIN)."""
    paused = data.get("paused", False)

    api_key_service = APIKeyService(db)
    result = await api_key_service.toggle_global_traffic_pause(paused, current_admin.id)
    return {"status": "success", "paused": result.traffic_paused}


@router.put("/settings/ip-whitelist")
async def update_global_ip_whitelist(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
):
    """Configura la lista blanca de IPs globales (Solo ADMIN)."""
    ips = data.get("ips", [])

    api_key_service = APIKeyService(db)
    result = await api_key_service.update_global_ip_whitelist(ips, current_admin.id)
    return {"status": "success", "ips": result}
