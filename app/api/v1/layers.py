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
from app.db.models.user import User
from app.schemas.layer import (
    FeatureCollectionSchema,
    LayerCategoryTreeItem,
    LayerCreate,
    LayerPublicResponse,
    LayerResponse,
)
from app.services.layers import LayerService
from app.services.storage import FileTooLargeError

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
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error procesando capa") from e


@router.get("/categories", response_model=List[str])
async def get_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Obtiene el listado de categorías únicas de las capas."""
    service = LayerService(db)
    return await service.get_categories(public_only=current_user is None)


@router.get("/categories/tree", response_model=List[LayerCategoryTreeItem])
async def get_categories_tree(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Obtiene categorias, subcategorias y conteo de capas."""
    service = LayerService(db)
    return await service.get_categories_tree(public_only=current_user is None)


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
    try:
        layer = await service.update_layer(layer_id, update_data, file=file, actor=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")

    return layer


@router.get("/features/properties", response_model=List[dict])
async def get_layers_features_properties(
    layer_ids: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    try:
        ids = [uuid.UUID(x.strip()) for x in layer_ids.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="IDs inválidos")

    service = LayerService(db)
    return await service.get_features_properties(ids, public_only=current_user is None)


@router.get("/features/{feature_id}", response_model=dict)
async def get_feature_detail(
    feature_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    service = LayerService(db)
    feature = await service.get_feature_by_id(feature_id, public_only=current_user is None)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature no encontrado")
    return feature


@router.get("/{layer_id}/field-values", response_model=dict)
async def get_field_values(
    layer_id: uuid.UUID,
    field: str = Query(..., description="Nombre del campo a consultar"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Valores únicos de un campo para simbología categorizada."""
    service = LayerService(db)
    return await service.get_field_values(layer_id, field, public_only=current_user is None)


@router.get("/{layer_id}/field-stats", response_model=dict)
async def get_field_stats(
    layer_id: uuid.UUID,
    field: str = Query(..., description="Nombre del campo numérico"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Estadísticas numéricas de un campo para simbología graduada."""
    service = LayerService(db)
    return await service.get_field_stats(layer_id, field, public_only=current_user is None)


@router.get("/{layer_id}/features", response_model=FeatureCollectionSchema)
async def get_layer_geojson(
    layer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Obtiene el GeoJSON de la capa. Accesible públicamente desde el frontend."""
    service = LayerService(db)
    return await service.get_layer_geojson(layer_id, public_only=current_user is None)


@router.delete("/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layer(
    layer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = LayerService(db)
    try:
        deleted = await service.delete_layer(layer_id, actor=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Capa no encontrada")
