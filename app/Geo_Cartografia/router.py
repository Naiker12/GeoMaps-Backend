from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db
from app.Geo_Usuarios.model import User
from app.schemas.cartografia import CartografiaGenerateRequest
from app.services.cartografia_service import CartografiaService
from app.services.cartografia.temporary_files import cleanup_generated_file

router = APIRouter()


@router.post("/generate")
async def generate_cartografia(
    request: CartografiaGenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = CartografiaService(db)
    path, media_type, filename = await service.generate_file(request)
    background_tasks.add_task(cleanup_generated_file, path)

    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=background_tasks,
        headers={"X-Generated-By": str(current_user.id)},
    )
