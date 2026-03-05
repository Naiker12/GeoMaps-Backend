
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.services.search_service import SearchService

router = APIRouter()

@router.get("/")
async def search(
    q: str = Query(..., min_length=2, description="Texto de búsqueda o coordenadas (lat, lon)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Endpoint de búsqueda global para el geoportal.
    """
    search_service = SearchService(db)
    result = await search_service.search(q)
    return result

@router.get("/suggestions")
async def get_suggestions(
    limit: int = 5,
    db: AsyncSession = Depends(get_db)
):
    """
    Endpoint para obtener sugerencias de búsqueda aleatorias.
    """
    search_service = SearchService(db)
    result = await search_service.get_suggestions(limit)
    return result
