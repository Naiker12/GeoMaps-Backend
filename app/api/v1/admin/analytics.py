"""Router de analítica para el panel administrativo.
Muy simplificado: toda la lógica reside en AnalyticsService.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.analytics import AnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/summary")
async def get_analytics_summary(db: AsyncSession = Depends(get_db)):
    """Resumen de KPIs de alto nivel para el Dashboard."""
    service = AnalyticsService(db)
    summary = await service.get_summary_kpis()
    return {"kpis": summary}


@router.get("/charts")
async def get_analytics_charts(
    range_days: int = Query(30, alias="range"),
    db: AsyncSession = Depends(get_db),
):
    """Datos para gráficas (Crecimiento, Actividad, Distribución)."""
    try:
        service = AnalyticsService(db)
        
        # Crecimiento y Actividad
        growth_data = await service.get_growth_data(range_days)
        
        # Actividad Reciente
        recent_activity = await service.get_recent_activity()
        
        # Distribución de Capas real (Puntos, Líneas, Polígonos)
        layer_types = await service.get_layer_distribution()
        
        # Consumo de Recursos (90 días por defecto para la gráfica de barras)
        resource_usage = await service.get_resource_usage()

        return {
            **growth_data,
            "layerTypes": layer_types,
            "recentActivity": recent_activity,
            "resourceUsage": resource_usage
        }
    except Exception as exc:
        logger.error("Error en analytics charts: %s", exc, exc_info=True)
        return {"error": "No se pudieron cargar los datos de analítica"}


@router.get("/usage")
async def get_system_usage(db: AsyncSession = Depends(get_db)):
    """Estado y consumo de recursos del sistema (DB, API, Tokens)."""
    service = AnalyticsService(db)
    return await service.get_system_status()
