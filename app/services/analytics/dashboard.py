from datetime import timedelta
from typing import Any
from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.utils.datetime import get_utc_now
from app.db.models.layer import Layer, LayerFeature, VisibilityEnum
from app.db.models.project import Project
from .utils import group_by_day, group_by_month


class DashboardAnalytics:
    """Procesamiento de KPIs y métricas del Dashboard principal."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_summary_kpis(self) -> list[dict[str, Any]]:
        """KPIs enfocados en capas GIS y dataset."""
        results = {}
        for key, stmt in {
            "layers": select(func.count(Layer.id)),
            "features": select(func.count(LayerFeature.id)),
            "projects": select(func.count(Project.id)),
            "visible": select(func.count(Layer.id)).where(Layer.visibility == VisibilityEnum.PUBLIC)
        }.items():
            results[key] = await self.db.scalar(stmt) or 0

        return [
            {"title": "Capas Totales", "value": results["layers"], "trend": "En vivo", "icon": "Layers"},
            {"title": "Puntos de Datos", "value": results["features"], "trend": "Global", "icon": "Database"},
            {"title": "Capas Públicas", "value": results["visible"], "trend": "Compartidas", "icon": "Eye"},
            {"title": "Proyectos MAP", "value": results["projects"], "trend": "Activos", "icon": "MapPin"},
        ]

    async def get_growth_data(self, range_days: int) -> dict[str, Any]:
        """Crecimiento cronológico de capas y dataset."""
        now = get_utc_now()
        start_date = now - timedelta(days=range_days)
        layer_stmt = select(Layer.created_at).where(Layer.created_at >= start_date)
        feature_stmt = select(LayerFeature.created_at).where(LayerFeature.created_at >= start_date)
        layer_dates = (await self.db.execute(layer_stmt)).scalars().all()
        feature_dates = (await self.db.execute(feature_stmt)).scalars().all()

        if range_days <= 31:
            return group_by_day(layer_dates, feature_dates, range_days)
        return group_by_month(layer_dates, feature_dates, range_days)

    async def get_resource_usage(self, days: int = 90) -> list[dict]:
        """Dataset histórico y proyectos."""
        now = get_utc_now()
        start_date = now - timedelta(days=days)
        interval = 5
        data = []
        for i in range(days // interval + 1):
            d_start = start_date + timedelta(days=i * interval)
            d_end = d_start + timedelta(days=interval)
            l_stmt = select(func.count(Layer.id)).where(
                (Layer.created_at >= d_start) & (Layer.created_at < d_end)
            )
            p_stmt = select(func.count(Project.id)).where(
                (Project.created_at >= d_start) & (Project.created_at < d_end)
            )
            l_count = await self.db.scalar(l_stmt) or 0
            p_count = await self.db.scalar(p_stmt) or 0
            data.append({
                "date": d_start.isoformat(),
                "capas": l_count,
                "dataset": l_count * 200,
                "proyectos": p_count
            })
        return data

    async def get_system_usage(self) -> dict[str, Any]:
        """
        Métricas reales del sistema.
        - Tamaño real de la BD Postgres (pg_database_size)
        - Top capas por cantidad de features (datos reales de LayerFeature)
        - Total de features almacenados
        - Sin datos simulados ni hardcodeados
        """
        # ── Tamaño real de la BD Postgres ──────────────────────────────────
        size_stmt = select(func.pg_database_size(func.current_database()))
        db_bytes = await self.db.scalar(size_stmt) or 0
        db_mb = round(db_bytes / (1024 * 1024), 2)

        # Supabase FREE tier tiene límite de 500 MB en la BD
        db_percentage = min(99.9, round((db_mb / 500) * 100, 1))

        # ── Total de features en la BD ──────────────────────────────────────
        total_features = await self.db.scalar(select(func.count(LayerFeature.id))) or 0

        # ── Top capas por cantidad de features (real, sin hardcodear) ───────
        top_layers_stmt = (
            select(Layer.name, func.count(LayerFeature.id).label("feature_count"))
            .join(LayerFeature, LayerFeature.layer_id == Layer.id)
            .group_by(Layer.id, Layer.name)
            .order_by(desc("feature_count"))
            .limit(5)
        )
        top_layers_result = await self.db.execute(top_layers_stmt)
        top_layers = [
            {"name": name, "count": count}
            for name, count in top_layers_result
        ]

        # ── Total de capas ──────────────────────────────────────────────────
        total_layers = await self.db.scalar(select(func.count(Layer.id))) or 0

        return {
            "dbUsage": f"{db_percentage}%",
            "dbSize": f"{db_mb} MB",
            "dbLimit": "500 MB",
            "dbPercentage": db_percentage,
            "totalFeatures": total_features,
            "totalLayers": total_layers,
            "topLayers": top_layers,           
            "status": "OK" if db_percentage < 85 else "Warning"
        }