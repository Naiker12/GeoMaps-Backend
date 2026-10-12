
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user_optional, get_db
from app.db.models.user import User
from app.services.search import SearchService

router = APIRouter()

@router.get("/")
async def search(
    q: str = Query(..., min_length=2, description="Texto de búsqueda o coordenadas (lat, lon)"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Endpoint de búsqueda global para el geoportal.
    """
    search_service = SearchService(db, public_only=current_user is None)
    try:
        result = await search_service.search(q)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result

@router.get("/suggestions")
async def get_suggestions(
    limit: int = Query(5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Endpoint para obtener sugerencias de búsqueda aleatorias.
    """
    search_service = SearchService(db, public_only=current_user is None)
    result = await search_service.get_suggestions(limit)
    return result

@router.post("/viewed")
async def mark_as_viewed(
    id: int = Query(..., gt=0),
    source: str = Query(..., pattern="^feature$"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Registra que un usuario seleccionó y visualizó un resultado de búsqueda.
    """
    search_service = SearchService(db, public_only=current_user is None)
    await search_service.log_view(id, source)
    return {"status": "ok"}
