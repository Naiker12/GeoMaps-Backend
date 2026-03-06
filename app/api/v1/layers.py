from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from typing import List, Any, Optional
import json

from app.api.deps import get_db, get_current_active_user, get_current_user_optional
from app.db.models.user import User
from app.schemas.layer import LayerResponse, LayerCreate, FeatureCollectionSchema
from app.services.layer_service import LayerService

router = APIRouter()

@router.post("/", response_model=LayerResponse, status_code=status.HTTP_201_CREATED)
async def upload_layer(
    name: str = Form(...),
    description: str = Form(None),
    category: str = Form(None),
    source: str = Form(None),
    visibility: str = Form("PRIVATE"),
    map_color: str = Form("#3ECF8E"),
    map_opacity: float = Form(0.8),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Sube un archivo .zip (Shapefile) o .geojson.
    Extrae, reproyecta (WGS84 EPSG:4326), inserta en BDD, sube archivo y devuelve metadatos.
    """
    layer_in = LayerCreate(
        name=name,
        description=description,
        category=category,
        source=source,
        visibility=visibility,
        map_color=map_color,
        map_opacity=map_opacity
    )
    
    layer_service = LayerService(db)
    
    try:
        layer = await layer_service.process_and_upload_layer(
            layer_in=layer_in,
            file=file,
            user_id=current_user.id
        )
        return layer
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error validando o procesando capa: {str(e)}")


@router.get("/", response_model=List[LayerResponse])
async def list_layers(
    visibility: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Obtiene todas las capas. Si el usuario no está autenticado, solo devuelve las públicas.
    """
    if current_user is None:
        visibility = "PUBLIC"
        
    layer_service = LayerService(db)
    layers = await layer_service.list_layers(visibility=visibility)
    return layers

@router.patch("/{layer_id}", response_model=LayerResponse)
async def update_layer(
    layer_id: uuid.UUID,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    visibility: Optional[str] = Form(None),
    map_color: Optional[str] = Form(None),
    map_opacity: Optional[float] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Actualiza metadatos de una capa (PATCH con FormData).
    """
    update_data = {}
    if name is not None: update_data["name"] = name
    if description is not None: update_data["description"] = description
    if category is not None: update_data["category"] = category
    if source is not None: update_data["source"] = source
    if visibility is not None: update_data["visibility"] = visibility
    if map_color is not None: update_data["map_color"] = map_color
    if map_opacity is not None: update_data["map_opacity"] = map_opacity

    layer_service = LayerService(db)
    updated_layer = await layer_service.update_layer(layer_id, update_data)
    
    if not updated_layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")
        
    return updated_layer

@router.get("/features/properties", response_model=List[dict])
async def get_layers_features_properties(
    layer_ids: str = Query(..., description="Comma separated layer IDs"),
    db: AsyncSession = Depends(get_db)
):
    """
    Obtiene solo las propiedades de las features de múltiples capas.
    """
    try:
        id_list = [uuid.UUID(lid.strip()) for lid in layer_ids.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de IDs de capa inválido.")
        
    layer_service = LayerService(db)
    return await layer_service.get_features_properties(id_list)

@router.get("/features/{feature_id}", response_model=dict)
async def get_feature_detail(
    feature_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Obtiene el detalle de una sola entidad (propiedades + geometría).
    """
    layer_service = LayerService(db)
    return await layer_service.get_feature_by_id(feature_id)

@router.get("/{layer_id}/features", response_model=FeatureCollectionSchema)
async def get_layer_geojson(
    layer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Obtiene un FeatureCollection con todas las geometrías de la capa.
    (Endpoint consumido por ArcGIS JS y visores).
    """
    layer_service = LayerService(db)
    geojson_data = await layer_service.get_layer_geojson(layer_id)
    return geojson_data

@router.delete("/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layer(
    layer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Elimina los metadatos y features (on delete cascade) de la base de datos.
    """
    layer_service = LayerService(db)
    await layer_service.delete_layer(layer_id)
    return None
