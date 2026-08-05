from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_optional, get_db
from app.Geo_Usuarios.model import User
from app.Geo_Soporte.schemas import SupportRequestCreate, SupportRequestResponse
from app.Geo_Soporte.service import SupportService

router = APIRouter()


@router.post(
    "/",
    response_model=SupportRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_support_request(
    request_in: SupportRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    metadata = dict(request_in.metadata_ or {})
    metadata.setdefault("user_agent", request.headers.get("user-agent"))
    metadata.setdefault("ip_address", request.client.host if request.client else None)
    request_in.metadata_ = metadata

    service = SupportService(db)
    return await service.create_request(
        request_in,
        user_id=current_user.id if current_user else None,
    )
