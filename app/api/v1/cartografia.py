import os
import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db
from app.db.models.user import User
from app.schemas.cartografia import CartografiaGenerateRequest
from app.services.cartografia_service import CartografiaService

router = APIRouter()


async def _cleanup_generated_file(path: str, delay_seconds: int = 60) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except PermissionError:
        # Windows can keep the file handle briefly after a streamed download.
        await asyncio.sleep(delay_seconds)
        try:
            os.unlink(path)
        except OSError:
            pass


@router.post("/generate")
async def generate_cartografia(
    request: CartografiaGenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = CartografiaService(db)
    path, media_type, filename = await service.generate_file(request)
    background_tasks.add_task(_cleanup_generated_file, path)

    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=background_tasks,
        headers={"X-Generated-By": str(current_user.id)},
    )
