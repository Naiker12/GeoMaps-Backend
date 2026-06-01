import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db
from app.db.models.user import User
from app.schemas.cartografia import CartografiaGenerateRequest
from app.services.cartografia_service import CartografiaService

router = APIRouter()


@router.post("/generate")
async def generate_cartografia(
    request: CartografiaGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = CartografiaService(db)
    path, media_type, filename = await service.generate_file(request)

    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=None,
        headers={"X-Generated-By": str(current_user.id)},
    )
