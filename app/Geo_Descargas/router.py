from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import json
from typing import List, Optional

from app.api.deps import get_db, get_current_active_user, get_current_user_optional
from app.Geo_Usuarios.model import User
from app.Geo_Descargas.schemas import DownloadResourceResponse, DownloadResourceCreate, DownloadResourceUpdate
from app.Geo_Descargas.service import DownloadService
from app.Geo_Descargas.storage import DownloadStorageService

router = APIRouter()

ALLOWED_EXTENSIONS = {"zip", "geojson", "json", "pdf", "shp", "csv", "xml"}

@router.post("/", response_model=DownloadResourceResponse, status_code=status.HTTP_201_CREATED)
async def create_download(
    name: str = Form(...),
    category: str = Form(...),
    layer_id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    metadata_: Optional[str] = Form(None, alias="metadata"),
    show_in_public: bool = Form(True),
    is_published: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Crea el registro inicial del recurso de descarga."""
    download_in = DownloadResourceCreate(
        name=name,
        category=category,
        layer_id=uuid.UUID(layer_id) if layer_id and layer_id not in ["undefined", "manual"] else None,
        description=description,
        metadata_=json.loads(metadata_) if metadata_ else {},
        show_in_public=show_in_public,
        is_published=is_published
    )
    
    download_service = DownloadService(db)
    return await download_service.create_download(download_in, current_user.id)


@router.post("/{resource_id}/upload")
async def upload_resource_file(
    resource_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # 0. Validar existencia y protección contra upload en capas vinculadas
    download_service = DownloadService(db)
    resource = await download_service.repository.get(resource_id)
    
    if not resource:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
        
    if resource.layer_id:
        raise HTTPException(
            status_code=400, 
            detail="Este recurso está vinculado a una capa cartográfica. No requiere subida manual."
        )

    ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
         raise HTTPException(status_code=400, detail=f"Extensión .{ext} no permitida")

    # 1. Análisis de metadatos (tipo geometría, conteo)
    metadata = await DownloadStorageService.analyze_file(file)
    
    # 2. Reinicio crítico del cursor para evitar subida vacía (0 bytes)
    await file.seek(0)
    
    # 3. Subida física al bucket Download
    storage_info = await DownloadStorageService.upload_resource_file(resource_id, file)
    
    # 4. Actualización de metadatos técnicos en base de datos
    updated = await download_service.update_resource_metadata(resource_id, {
        **storage_info,
        **metadata
    })
    
    if not updated:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
        
    return updated


@router.get("/", response_model=List[DownloadResourceResponse])
async def list_admin_downloads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Lista todos los recursos de descarga para el panel de administración."""
    download_service = DownloadService(db)
    return await download_service.get_downloads()


@router.get("/public", response_model=dict)
async def list_public_downloads(
    db: AsyncSession = Depends(get_db)
):
    """Lista recursos de descarga agrupados por categoría para el portal público."""
    download_service = DownloadService(db)
    downloads = await download_service.get_downloads(show_in_public=True)
    
    grouped = {}
    for item in downloads:
        if item.category not in grouped:
            grouped[item.category] = []
        item_dict = {
            "id": str(item.id),
            "name": item.name,
            "category": item.category,
            "description": item.description,
            "metadata": item.metadata_,
            "file_url": item.file_url,
            "file_format": item.file_format,
            "file_size_bytes": item.file_size_bytes,
            "content_count": item.content_count,
            "geometry_type": item.geometry_type,
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
    """Elimina el recurso físico de Supabase y luego el registro en DB."""
    download_service = DownloadService(db)
    resource = await download_service.repository.get(download_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")

    if resource.file_path:
        await DownloadStorageService.delete_resource_files(download_id, resource.file_path)

    success = await download_service.delete_download(download_id)
    if not success:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
        
    return None
