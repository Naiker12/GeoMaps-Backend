import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db
from app.db.models.user import User
from app.schemas.api_key import APIKeyCreate, APIKeyResponse, APIKeyUpdate
from app.services.api_key_service import APIKeyService

router = APIRouter()


@router.post("/", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    api_key_in: APIKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Genera una nueva API Key para el usuario actual."""
    api_key_service = APIKeyService(db)
    api_key, raw_key = await api_key_service.create_api_key(current_user.id, api_key_in)

    # Adjuntar la clave cruda en la respuesta (visible solo una vez)
    response = APIKeyResponse.model_validate(api_key)
    response.key = raw_key
    return response


@router.get("/", response_model=List[APIKeyResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Lista todas las API Keys (activas y revocadas) del usuario."""
    api_key_service = APIKeyService(db)
    keys = await api_key_service.list_user_keys(current_user.id)
    return keys


@router.patch("/{key_id}/revoke", response_model=APIKeyResponse)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Revoca una API Key existente."""
    api_key_service = APIKeyService(db)
    revoked = await api_key_service.revoke_api_key(key_id, current_user.id)
    if not revoked:
        raise HTTPException(
            status_code=404, detail="API Key no encontrada o no pertenece al usuario."
        )
    return revoked


@router.get("/stats")
async def get_my_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Obtiene métricas de uso de API reales para el usuario actual."""
    api_key_service = APIKeyService(db)
    return await api_key_service.get_user_stats_summary(current_user.id)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Elimina permanentemente una API Key."""
    api_key_service = APIKeyService(db)
    success = await api_key_service.delete_api_key(key_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="API Key no encontrada.")
    return None
