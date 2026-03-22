from sqlalchemy.ext.asyncio import AsyncSession
from .dashboard import DashboardAnalytics
from .layers import LayerAnalytics
from .activity import ActivityAnalytics

class AnalyticsService:
    """Facade que centraliza los sub-servicios de analítica de GeoMaps."""
    def __init__(self, db: AsyncSession):
        self.db = db
        # Instancias de servicios especializados
        self.dashboard_svc = DashboardAnalytics(db)
        self.layers_svc = LayerAnalytics(db)
        self.activity_svc = ActivityAnalytics(db)

    async def get_summary_kpis(self):
        """KPIs de alto nivel para el Dashboard."""
        return await self.dashboard_svc.get_summary_kpis()

    async def get_growth_data(self, range_days: int):
        """Tendencia de crecimiento de capas/dataset."""
        return await self.dashboard_svc.get_growth_data(range_days)

    async def get_recent_activity(self, limit: int = 50):
        """Últimas acciones registradas."""
        return await self.activity_svc.get_recent(limit)

    async def get_layer_distribution(self):
        """Distribución real por geometría."""
        return await self.layers_svc.get_distribution()

    async def get_resource_usage(self, days: int = 90):
        """Dataset histórico y proyectos creados."""
        return await self.dashboard_svc.get_resource_usage(days)

    async def get_system_status(self):
        """Estado resumido del sistema (Estilo Supabase Status Bar)."""
        return await self.dashboard_svc.get_system_usage()

    async def get_layer_stats(self):
        """Top de capas por densidad de información (Features)."""
        return await self.layers_svc.get_stats()
