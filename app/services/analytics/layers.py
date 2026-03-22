from typing import Any
from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.layer import Layer, LayerFeature

class LayerAnalytics:
    """Análisis detallado de metadatos y distribución de capas GIS."""
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_distribution(self) -> list[dict]:
        """Distribución por categoría lógica de la capa (EDUCACION, SALUD, etc.)."""
        stmt = select(Layer.category, func.count(Layer.id)).group_by(Layer.category)
        result = await self.db.execute(stmt)
        return [
            {"type": str(cat).upper() if cat else "SIN CATEGORÍA", "count": count}
            for cat, count in result
        ]

    async def get_stats(self) -> dict[str, Any]:
        """Estadísticas de densidad de datos (top capas por features)."""
        stmt = (
            select(Layer.name, func.count(LayerFeature.id).label("features"))
            .join(LayerFeature)
            .group_by(Layer.id, Layer.name)
            .order_by(desc("features"))
            .limit(5)
        )
        result = await self.db.execute(stmt)
        top_layers = [{"name": name, "count": count} for name, count in result]
        return {
            "topLayers": top_layers,
            "totalFeatures": await self.db.scalar(select(func.count(LayerFeature.id))) or 0
        }
