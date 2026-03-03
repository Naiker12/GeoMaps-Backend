from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
import uuid
from typing import List, Any
import json

from app.api.deps import get_db, get_current_active_user
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
    visibility: str = Form("private"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
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
        visibility=visibility
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
        # Aquí se capturan errores de GeoPandas o base de datos.
        raise HTTPException(status_code=500, detail=f"Error validando o procesando capa: {str(e)}")


@router.get("/", response_model=List[LayerResponse])
async def list_layers(
    visibility: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Obtiene todas las capas, con opción a filtrar por visibilidad.
    """
    layer_service = LayerService(db)
    layers = await layer_service.list_layers(visibility=visibility)
    return layers


@router.get("/{layer_id}/features", response_model=FeatureCollectionSchema)
async def get_layer_geojson(
    layer_id: uuid.UUID,
    db: Session = Depends(get_db),
    # Descomentar e importar User si require auth, lo dejamos libre o validado según caso de uso
    # current_user: User = Depends(get_current_active_user)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Elimina los metadatos y features (on delete cascade) de la base de datos.
    Nota: Se debe borrar también de Storage si se desea limpieza total.
    """
    layer_service = LayerService(db)
    await layer_service.delete_layer(layer_id)
    return None
