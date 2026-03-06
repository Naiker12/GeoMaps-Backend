from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import json
from typing import List, Optional

from app.api.deps import get_db, get_current_active_user, get_current_user_optional
from app.db.models.user import User
from app.schemas.download import DownloadResourceResponse, DownloadResourceCreate, DownloadResourceUpdate
from app.services.download_service import DownloadService

router = APIRouter()

@router.post("/", response_model=DownloadResourceResponse, status_code=status.HTTP_201_CREATED)
async def create_download(
    name: str = Form(...),
    category: str = Form(...),
    layer_id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    metadata_: Optional[str] = Form(None, alias="metadata"),
    show_in_public: bool = Form(True),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Crea un nuevo recurso de descarga, opcionalmente con un archivo estático.
    """
    download_in = DownloadResourceCreate(
        name=name,
        category=category,
        layer_id=uuid.UUID(layer_id) if layer_id and layer_id != "undefined" and layer_id != "manual" else None,
        description=description,
        metadata_=json.loads(metadata_) if metadata_ else {},
        show_in_public=show_in_public
    )
    
    download_service = DownloadService(db)
    
    try:
        files = [file] if file else []
        download = await download_service.create_download(
            download_in=download_in,
            user_id=current_user.id,
            files=files
        )
        return download
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error validando o procesando recurso: {str(e)}")


@router.get("/", response_model=List[DownloadResourceResponse])
async def list_admin_downloads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Lista todos los recursos de descarga para el panel de administración.
    """
    download_service = DownloadService(db)
    return await download_service.get_downloads()


@router.get("/public", response_model=dict)
async def list_public_downloads(
    db: AsyncSession = Depends(get_db)
):
    """
    Lista recursos de descarga agrupados por categoría para el portal público.
    """
    download_service = DownloadService(db)
    downloads = await download_service.get_downloads(show_in_public=True)
    
    grouped = {}
    for item in downloads:
        if item.category not in grouped:
            grouped[item.category] = []
        # Convert SQLAlchemy obj to dict
        item_dict = {
            "id": str(item.id),
            "name": item.name,
            "category": item.category,
            "description": item.description,
            "metadata": item.metadata_,
            "file_url": item.file_url,
            "layer_id": str(item.layer_id) if item.layer_id else None,
            "created_at": item.created_at.isoformat()
        }
        grouped[item.category].append(item_dict)
        
    return grouped


@router.delete("/{download_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_download(
    download_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Elimina un recurso de descarga.
    """
    download_service = DownloadService(db)
    success = await download_service.delete_download(download_id)
    if not success:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
        
    return None
