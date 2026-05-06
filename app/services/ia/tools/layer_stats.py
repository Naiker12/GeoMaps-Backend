import logging
from typing import Any, Dict

from sqlalchemy import text

logger = logging.getLogger(__name__)


class LayerStatsTools:
    async def listar_campos_capa(self, layer_name: str) -> Dict[str, Any]:
        """Obtiene campos disponibles de una capa para analisis."""
        try:
            stmt = text("""
                SELECT properties
                FROM layer_features
                JOIN layers ON layers.id = layer_features.layer_id
                WHERE unaccent(layers.name) ILIKE unaccent(:name)
                LIMIT 5
            """)
            result = await self.db.execute(stmt, {"name": f"%{layer_name}%"})
            rows = result.fetchall()

            if not rows:
                return {"success": False, "error": f"No se encontraron datos para la capa '{layer_name}'."}

            all_keys = set()
            for row in rows:
                if row[0]:
                    all_keys.update(row[0].keys())

            fields = sorted(all_keys)
            return {
                "success": True,
                "layer": layer_name,
                "fields": fields,
                "mensaje": f"La capa '{layer_name}' tiene estos campos disponibles: {', '.join(fields)}.",
            }
        except Exception as exc:
            logger.error("Error en listar_campos_capa: %s", exc)
            return {"success": False, "error": str(exc)}

    async def consultar_estadisticas_capa(
        self,
        layer_name: str,
        field: str = "estrato",
        chart_type: str = "bar",
        include_chart: bool = True,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Obtiene distribucion de valores de un campo en una capa."""
        try:
            requested_chart_type = (chart_type or "bar").lower()
            max_chart_categories = 8 if requested_chart_type == "pie" else 15
            query_limit = max(1, min(int(limit or max_chart_categories), max_chart_categories))
            grouped_limit = max(1, query_limit - 1)
            stmt_layer = text("SELECT id FROM public.layers WHERE unaccent(name) ILIKE unaccent(:name) LIMIT 1")
            res_layer = await self.db.execute(stmt_layer, {"name": f"%{layer_name}%"})
            layer_id = res_layer.scalar()

            if not layer_id:
                return {"success": False, "error": f"Capa '{layer_name}' no encontrada."}

            stmt_total = text("""
                SELECT count(*)
                FROM layer_features
                WHERE layer_id = :lid
                  AND properties->>:field IS NOT NULL
            """)
            total_result = await self.db.execute(stmt_total, {"field": field, "lid": layer_id})
            total_records = int(total_result.scalar() or 0)

            stmt_stats = text("""
                SELECT
                    properties->>:field as category,
                    count(*) as total
                FROM layer_features
                WHERE layer_id = :lid
                GROUP BY 1
                ORDER BY 2 DESC
                LIMIT :limit
            """)
            result = await self.db.execute(
                stmt_stats,
                {"field": field, "lid": layer_id, "limit": grouped_limit},
            )
            rows = result.fetchall()

            data = [{"name": str(row[0] or "N/A"), "value": row[1]} for row in rows]
            visible_total = sum(item["value"] for item in data)
            other_value = max(0, total_records - visible_total)
            if other_value:
                data.append({"name": "Otros", "value": other_value})

            total = total_records or sum(item["value"] for item in data)

            response = {
                "success": True,
                "layer": layer_name,
                "field": field,
                "total": total,
                "data": data,
                "map_actions": [
                    {
                        "map_action": "toggle_layer",
                        "layer_name": layer_name,
                        "visible": True,
                    }
                ],
                "mensaje": f"Se analizaron {total} registros en la capa {layer_name} basados en {field}.",
            }

            if include_chart:
                response["analytics_data"] = {
                    "type": requested_chart_type,
                    "title": f"Distribucion de {field.replace('_', ' ').capitalize()}",
                    "layer_name": layer_name,
                    "label": field.replace("_", " ").capitalize(),
                    "subtitle": f"{total} registros analizados; se muestran {len(data)} grupos para una lectura clara",
                    "insight": f"El valor frecuente es {data[0]['name'] if data else 'N/A'} con {data[0]['value'] if data else 0} registros.",
                    "data": data,
                    "keys": ["value"],
                    "total_records": total,
                    "display_limit": max_chart_categories,
                    "grouped_others": bool(other_value),
                    "pdf_export": True,
                }

            return response
        except Exception as exc:
            logger.error("Error en consultar_estadisticas_capa: %s", exc)
            return {"success": False, "error": str(exc)}
