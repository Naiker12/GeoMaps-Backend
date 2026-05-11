import logging
from typing import Any, Dict, List

from sqlalchemy import text

logger = logging.getLogger(__name__)


class ZoneAnalysisTools:
    async def analizar_zona_extent(self, bbox: List[float]) -> Dict[str, Any]:
        """Realiza un resumen estadistico por capas dentro de un bbox."""
        try:
            xmin, ymin, xmax, ymax = bbox
            stmt = text("""
                SELECT
                    l.name as layer_name,
                    count(*) as count
                FROM layer_features lf
                JOIN layers l ON l.id = lf.layer_id
                WHERE lf.geom && ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
                GROUP BY l.name
                ORDER BY count DESC
            """)
            result = await self.db.execute(
                stmt,
                {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
            )
            rows = result.fetchall()

            breakdown = [{"name": row[0], "value": row[1]} for row in rows]
            total_features = sum(item["value"] for item in breakdown)
            total_layers = len(breakdown)

            return {
                "success": True,
                "bbox": bbox,
                "data": {
                    "total_elementos": total_features,
                    "capas_afectadas": total_layers,
                    "desglose": breakdown,
                },
                "analytics_data": {
                    "type": "table",
                    "title": "Analisis de Cobertura en Zona",
                    "subtitle": f"Se identificaron {total_features} elementos en {total_layers} categorias",
                    "data": breakdown,
                    "columns": [
                        {"key": "name", "label": "Capa"},
                        {"key": "value", "label": "Cantidad"},
                    ],
                    "report_available": True,
                },
                "mensaje": f"He analizado el area seleccionada y encontre {total_features} elementos distribuidos en {total_layers} capas.",
            }
        except Exception as exc:
            logger.error("Error en analizar_zona_extent: %s", exc)
            return {"success": False, "error": str(exc)}
