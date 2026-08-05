import json
import uuid
from typing import List, Optional, Union

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_current_user_optional, get_db
from app.Geo_Usuarios.model import User
from app.Geo_Capas.schemas import (
    FeatureCollectionSchema,
    LayerCategoryTreeItem,
    LayerCreate,
    LayerPublicResponse,
    LayerResponse,
)
from app.Geo_Capas.service import LayerService

router = APIRouter()


@router.post("/", response_model=LayerResponse, status_code=status.HTTP_201_CREATED)
async def upload_layer(
    name: str = Form(...),
    description: str = Form(None),
    category: str = Form(None),
    subcategory: str = Form(None),
    source: str = Form(None),
    visibility: str = Form("PRIVATE"),
    map_color: str = Form("#3ECF8E"),
    map_opacity: float = Form(0.8),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    layer_in = LayerCreate(
        name=name,
        description=description,
        category=category,
        subcategory=subcategory,
        source=source,
        visibility=visibility,
        map_color=map_color,
        map_opacity=map_opacity,
    )

    service = LayerService(db)

    try:
        return await service.process_and_upload_layer(
            layer_in=layer_in,
            file=file,
            user_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando capa: {str(e)}")


@router.get("/categories", response_model=List[str])
async def get_categories(
    db: AsyncSession = Depends(get_db),
):
    """Obtiene el listado de categorías únicas de las capas."""
    service = LayerService(db)
    return await service.get_categories()


@router.get("/categories/tree", response_model=List[LayerCategoryTreeItem])
async def get_categories_tree(
    db: AsyncSession = Depends(get_db),
):
    """Obtiene categorias, subcategorias y conteo de capas."""
    service = LayerService(db)
    return await service.get_categories_tree()


@router.get("/", response_model=List[Union[LayerResponse, LayerPublicResponse]])
async def list_layers(
    visibility: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    if current_user is None:
        visibility = "PUBLIC"

    service = LayerService(db)
    layers = await service.list_layers(
        visibility=visibility,
        category=category,
        subcategory=subcategory,
    )

    # Sin auth: serializar sin file_url
    if current_user is None:
        return [LayerPublicResponse.model_validate(layer) for layer in layers]

    return layers


@router.patch("/{layer_id}", response_model=LayerResponse)
async def update_layer(
    layer_id: uuid.UUID,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    subcategory: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    visibility: Optional[str] = Form(None),
    map_color: Optional[str] = Form(None),
    map_opacity: Optional[float] = Form(None),
    symbology: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    update_data = {}

    if name is not None:
        update_data["name"] = name
    if description is not None:
        update_data["description"] = description
    if category is not None:
        update_data["category"] = category
    if subcategory is not None:
        update_data["subcategory"] = subcategory
    if source is not None:
        update_data["source"] = source
    if visibility is not None:
        update_data["visibility"] = visibility
    if map_color is not None:
        update_data["map_color"] = map_color
    if map_opacity is not None:
        update_data["map_opacity"] = map_opacity

    if symbology is not None:
        try:
            update_data["symbology"] = json.loads(symbology)
        except Exception:
            raise HTTPException(status_code=400, detail="Simbología inválida")

    service = LayerService(db)
    layer = await service.update_layer(layer_id, update_data, file=file)

    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")

    return layer


@router.get("/features/properties", response_model=List[dict])
async def get_layers_features_properties(
    layer_ids: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        ids = [uuid.UUID(x.strip()) for x in layer_ids.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="IDs inválidos")

    service = LayerService(db)
    return await service.get_features_properties(ids)


@router.get("/features/{feature_id}", response_model=dict)
async def get_feature_detail(
    feature_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = LayerService(db)
    return await service.get_feature_by_id(feature_id)


@router.get("/{layer_id}/field-values", response_model=dict)
async def get_field_values(
    layer_id: uuid.UUID,
    field: str = Query(..., description="Nombre del campo a consultar"),
    db: AsyncSession = Depends(get_db),
):
    """Valores únicos de un campo para simbología categorizada."""
    service = LayerService(db)
    return await service.get_field_values(layer_id, field)


@router.get("/{layer_id}/field-stats", response_model=dict)
async def get_field_stats(
    layer_id: uuid.UUID,
    field: str = Query(..., description="Nombre del campo numérico"),
    db: AsyncSession = Depends(get_db),
):
    """Estadísticas numéricas de un campo para simbología graduada."""
    service = LayerService(db)
    return await service.get_field_stats(layer_id, field)


@router.get("/{layer_id}/features", response_model=FeatureCollectionSchema)
async def get_layer_geojson(
    layer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Obtiene el GeoJSON de la capa. Accesible públicamente desde el frontend."""
    service = LayerService(db)
    return await service.get_layer_geojson(layer_id)


@router.delete("/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layer(
    layer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = LayerService(db)
    await service.delete_layer(layer_id)
