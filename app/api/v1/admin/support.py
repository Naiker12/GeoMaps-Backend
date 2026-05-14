import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.support import (
    SupportRequestListResponse,
    SupportRequestResponse,
    SupportRequestUpdate,
)
from app.services.support_service import SupportService

router = APIRouter()


@router.get("/", response_model=SupportRequestListResponse)
async def list_support_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    service = SupportService(db)
    items, total = await service.list_requests(
        status=status_filter,
        search=search,
        page=page,
        limit=limit,
    )
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/{request_id}", response_model=SupportRequestResponse)
async def get_support_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = SupportService(db)
    support_request = await service.get_request(request_id)
    if not support_request:
        raise HTTPException(status_code=404, detail="Solicitud de soporte no encontrada")
    return support_request


@router.patch("/{request_id}", response_model=SupportRequestResponse)
async def update_support_request(
    request_id: uuid.UUID,
    request_in: SupportRequestUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = SupportService(db)
    support_request = await service.update_request(request_id, request_in)
    if not support_request:
        raise HTTPException(status_code=404, detail="Solicitud de soporte no encontrada")
    return support_request


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_support_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = SupportService(db)
    support_request = await service.get_request(request_id)
    if not support_request:
        raise HTTPException(status_code=404, detail="Solicitud de soporte no encontrada")

    await db.delete(support_request)
    await db.commit()
    return None
