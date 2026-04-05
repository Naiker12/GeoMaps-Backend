import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

class IAToolsService:
    """Bridge between AI models and GeoMaps Database/Services via Function Calling."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.search_service = SearchService(db)

    async def consultar_predios(self, query_texto: str, limit: int = 10) -> Dict[str, Any]:
        """Busca predios o información geográfica relevante en la base de datos."""
        try:
            results = await self.search_service.search(query_texto)
            # Limitar resultados para no saturar el contexto del LLM
            if results.get("features"):
                results["features"] = results["features"][:limit]
            return results
        except Exception as e:
            logger.error(f"Error en consultar_predios: {e}")
            return {"error": str(e)}


    async def listar_capas_activas(self, user_id: str) -> List[Dict[str, Any]]:
        """Lista las capas de datos que el usuario tiene disponibles o activas."""
        try:
            stmt = text("""
                SELECT id, name, type, is_visible, source
                FROM layers
                WHERE is_active = true
            """)
            result = await self.db.execute(stmt)
            rows = result.mappings().all()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error en listar_capas_activas: {e}")
            return []

    async def analizar_zona_extent(self, xmin: float, ymin: float, xmax: float, ymax: float) -> Dict[str, Any]:
        """Realiza un resumen estadístico de lo que hay en un área específica (bbox)."""
        try:
            stmt = text("""
                SELECT 
                    count(*) as total_features,
                    count(DISTINCT layer_id) as total_layers
                FROM layer_features
                WHERE geom && ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
            """)
            result = await self.db.execute(stmt, {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax})
            row = result.mappings().one()
            
            return {
                "bbox": [xmin, ymin, xmax, ymax],
                "total_elementos": row["total_features"],
                "capas_afectadas": row["total_layers"],
                "mensaje": "Análisis espacial completado para el extent proporcionado."
            }
        except Exception as e:
            logger.error(f"Error en analizar_zona_extent: {e}")
            return {"error": str(e)}

    async def obtener_consumo_ia(self, user_id: str) -> Dict[str, Any]:
        """Obtiene métricas de consumo de IA para el usuario actual (Auditoría)."""
        try:
            stmt = text("""
                SELECT 
                    count(*) as total_requests,
                    sum(tokens_input + tokens_output) as total_tokens,
                    sum(cost) as total_cost
                FROM ia_audit_logs
                WHERE user_id = (:user_id)::uuid
                AND created_at > now() - interval '30 days'
            """)
            result = await self.db.execute(stmt, {"user_id": user_id})
            daily_stmt = text("SELECT count(*) FROM ia_audit_logs WHERE user_id = (:uid)::uuid AND created_at >= date_trunc('day', now()) AND status = 'success'")
            daily_count = (await self.db.execute(daily_stmt, {"uid": user_id})).scalar() or 0
            
            return {
                "requests_3d": row["total_requests"] or 0,
                "tokens_30d": row["total_tokens"] or 0,
                "costo_30d_usd": float(row["total_cost"] or 0),
                "mensajes_hoy": daily_count,
                "limite_diario": 10,
                "limite_mensual": 5.00
            }
        except Exception as e:
            logger.error(f"Error en obtener_consumo_ia: {e}")
            return {"error": str(e)}
