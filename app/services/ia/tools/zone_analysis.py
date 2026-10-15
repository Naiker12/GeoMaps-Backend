import logging
from typing import Any, Dict, List

from sqlalchemy import text
from app.services.ia.geo_context import normalize_extent_to_bbox

logger = logging.getLogger(__name__)


class ZoneAnalysisTools:
    async def analizar_zona_extent(self, bbox: List[float]) -> Dict[str, Any]:
        """Realiza un resumen estadistico por capas dentro de un bbox."""
        try:
            bbox = normalize_extent_to_bbox(bbox)
            if bbox is None:
                return {"success": False, "needs_clarification": True, "error": "Selecciona un área del mapa para analizarla"}
            xmin, ymin, xmax, ymax = bbox
            stmt = text("""
                SELECT
                    l.name as layer_name,
                    count(*) as count
                FROM layer_features lf
                JOIN layers l ON l.id = lf.layer_id
                WHERE l.visibility = 'PUBLIC'
                  AND lf.geom && ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
                  AND CASE WHEN ST_IsValid(lf.geom)
                      THEN ST_Intersects(lf.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)) ELSE FALSE END
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
                    "title": "Elementos que intersectan el área seleccionada",
                    "subtitle": f"Se identificaron {total_features} elementos en {total_layers} categorias",
                    "data": breakdown,
                    "columns": [
                        {"key": "name", "label": "Capa"},
                        {"key": "value", "label": "Cantidad"},
                    ],
                    "report_available": True,
                },
                "analysis": {"source": "PostGIS", "bbox": bbox, "method": "ST_Intersects", "total_features": total_features,
                             "warnings": ["Conteo de elementos; no representa porcentaje de cobertura. Se excluyen geometrías inválidas y capas privadas."]},
                "mensaje": f"He analizado el area seleccionada y encontre {total_features} elementos distribuidos en {total_layers} capas.",
            }
        except Exception as exc:
            logger.error("Error en analizar_zona_extent: %s", exc)
            return {"success": False, "error": str(exc)}
