import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

logger = logging.getLogger(__name__)

PRIORITY_FIELD_NAMES = [
    "nombre", "name", "nom", "descripcion", "description",
    "tipo", "type", "categoria", "category", "clase", "class",
    "institucion", "entidad", "establecimiento", "puesto", "sitio",
    "estado", "modalidad", "nivel", "uso",
    "localidad", "barrio", "comuna", "sector", "zona", "area",
]

EXCLUDE_FIELD_NAMES = [
    "id", "gid", "objectid", "fid", "shape_area", "shape_len",
    "geom", "geometry", "lat", "lon", "latitude", "longitude",
    "x", "y", "total", "cantidad", "count", "num", "numero",
    "codigo", "code", "cod", "pk", "globalid",
]

BROAD_LOCATION_FIELD_NAMES = {"localidad", "barrio", "comuna", "sector", "zona", "area"}


def _normalize_field_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_excluded_field(field: str) -> bool:
    normalized = _normalize_field_name(field)
    return any(token == normalized or token in normalized for token in EXCLUDE_FIELD_NAMES)


def _looks_numeric(values: List[Any]) -> bool:
    cleaned = [value for value in values if value not in (None, "")]
    if not cleaned:
        return False
    numeric_count = 0
    for value in cleaned:
        try:
            float(str(value).replace(",", "."))
            numeric_count += 1
        except (TypeError, ValueError):
            pass
    return numeric_count / len(cleaned) >= 0.8


def _is_pure_number(value: Any) -> bool:
    try:
        float(str(value).replace(",", "."))
        return True
    except (TypeError, ValueError):
        return False


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

    async def _get_layer_id(self, layer_name: str) -> Tuple[Optional[Any], Optional[str]]:
        stmt = text("SELECT id, name FROM public.layers WHERE unaccent(name) ILIKE unaccent(:name) LIMIT 1")
        result = await self.db.execute(stmt, {"name": f"%{layer_name}%"})
        row = result.fetchone()
        if not row:
            return None, None
        return row[0], str(row[1])

    async def _get_sample_properties(self, layer_id: Any, limit: int = 50) -> List[Dict[str, Any]]:
        stmt = text("""
            SELECT properties
            FROM layer_features
            WHERE layer_id = :lid
              AND properties IS NOT NULL
            LIMIT :limit
        """)
        result = await self.db.execute(stmt, {"lid": layer_id, "limit": limit})
        return [row[0] or {} for row in result.fetchall()]

    async def _get_best_chart_field(
        self,
        layer_id: Any,
        requested_field: Optional[str],
    ) -> Tuple[str, Dict[str, Any]]:
        samples = await self._get_sample_properties(layer_id)
        field_values: Dict[str, List[Any]] = {}
        original_keys: Dict[str, str] = {}

        for props in samples:
            for key, value in props.items():
                normalized = _normalize_field_name(key)
                original_keys.setdefault(normalized, str(key))
                field_values.setdefault(normalized, []).append(value)

        metadata = {
            "field_changed": False,
            "original_field_requested": requested_field,
            "warnings": [],
        }

        if not field_values:
            return requested_field or "id", metadata

        requested_key = _normalize_field_name(requested_field or "")
        if (
            requested_key in field_values
            and not _is_excluded_field(requested_key)
            and requested_key not in BROAD_LOCATION_FIELD_NAMES
        ):
            if not _looks_numeric(field_values[requested_key]):
                return original_keys[requested_key], metadata
            metadata["warnings"].append(
                f"Se evito graficar '{requested_field}' porque parece ser un campo numerico."
            )
        elif requested_key in BROAD_LOCATION_FIELD_NAMES:
            metadata["warnings"].append(
                f"Se priorizo un campo descriptivo en lugar de '{requested_field}' para evitar una grafica administrativa poco util."
            )

        text_candidates = [
            key for key, values in field_values.items()
            if not _is_excluded_field(key) and not _looks_numeric(values)
        ]

        for priority in PRIORITY_FIELD_NAMES:
            for key in text_candidates:
                if priority in key:
                    selected = original_keys[key]
                    metadata["field_changed"] = bool(requested_field and _normalize_field_name(selected) != requested_key)
                    return selected, metadata

        if text_candidates:
            selected = original_keys[text_candidates[0]]
            metadata["field_changed"] = bool(requested_field and _normalize_field_name(selected) != requested_key)
            return selected, metadata

        fallback_candidates = [key for key in field_values if not _is_excluded_field(key)]
        selected = original_keys[fallback_candidates[0]] if fallback_candidates else (requested_field or "id")
        metadata["field_changed"] = bool(requested_field and _normalize_field_name(selected) != requested_key)
        metadata["warnings"].append(
            f"No se encontro un campo descriptivo para graficar; se uso '{selected}'."
        )
        return selected, metadata

    def _generate_distribution_insight(
        self,
        data: List[Dict[str, Any]],
        field_used: str,
        total: int,
    ) -> Tuple[str, str]:
        if not data:
            return "No se encontraron datos para esta distribucion.", "warning"

        top = data[0]
        top_name = top.get("name", "N/A")
        top_value = int(top.get("value") or top.get("count") or 0)
        pct = round((top_value / total) * 100, 1) if total else 0

        if _is_pure_number(top_name):
            return (
                f"El campo '{field_used}' tiene distribucion numerica. "
                f"El valor mas frecuente es {top_name} con {top_value} registros ({pct}%). "
                "Para una lectura mas util, pide un campo descriptivo como nombre, tipo o categoria."
            ), "numeric_field"

        dominance = "concentracion alta" if pct > 50 else "distribucion variada"
        return (
            f"'{top_name}' es la categoria principal con {top_value} registros "
            f"({pct}% del total). La capa muestra {dominance} entre sus categorias."
        ), "info"

    async def consultar_estadisticas_capa(
        self,
        layer_name: str,
        field: str = "estrato",
        chart_type: str = "bar",
        include_chart: bool = True,
        limit: int = 8,
    ) -> Dict[str, Any]:
        """Obtiene distribucion de valores usando un campo descriptivo y legible."""
        try:
            requested_chart_type = (chart_type or "bar").lower()
            max_chart_categories = 8
            query_limit = max(1, min(int(limit or max_chart_categories), max_chart_categories))
            grouped_limit = max(1, query_limit - 1)

            layer_id, resolved_layer_name = await self._get_layer_id(layer_name)
            if not layer_id:
                return {"success": False, "error": f"Capa '{layer_name}' no encontrada."}

            original_field = field
            field, field_metadata = await self._get_best_chart_field(layer_id, field)

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
                  AND properties->>:field IS NOT NULL
                GROUP BY 1
                ORDER BY 2 DESC
                LIMIT :limit
            """)
            result = await self.db.execute(stmt_stats, {"field": field, "lid": layer_id, "limit": grouped_limit})
            rows = result.fetchall()

            all_categories = [
                {
                    "name": str(row[0] or "Sin datos"),
                    "value": int(row[1] or 0),
                    "count": int(row[1] or 0),
                    "is_others": False,
                }
                for row in rows
            ]
            data = all_categories[:]
            visible_total = sum(item["value"] for item in data)
            other_value = max(0, total_records - visible_total)
            if other_value > 0:
                data.append({
                    "name": f"Otros ({other_value} registros)",
                    "value": other_value,
                    "count": other_value,
                    "is_others": True,
                })

            total = total_records if total_records > 0 else visible_total
            for item in data:
                item["percentage"] = round((int(item["value"]) / total) * 100, 1) if total else 0
            for item in all_categories:
                item["percentage"] = round((int(item["value"]) / total) * 100, 1) if total else 0

            insight, insight_type = self._generate_distribution_insight(data, field, total)
            layer_label = resolved_layer_name or layer_name
            field_label = field.replace("_", " ").title()

            response = {
                "success": True,
                "layer": layer_label,
                "field": field,
                "field_used": field,
                "field_label": field_label,
                "field_changed": bool(field_metadata.get("field_changed")),
                "original_field_requested": original_field,
                "warnings": field_metadata.get("warnings", []),
                "total": total,
                "data": data,
                "map_actions": [
                    {"map_action": "toggle_layer", "layer_name": layer_label, "visible": True}
                ],
                "mensaje": (
                    f"Analisis de la capa '{layer_label}' por el campo '{field}'. "
                    f"Se identificaron {total} registros validos."
                ),
            }

            if include_chart:
                response["analytics_data"] = {
                    "type": "bar" if requested_chart_type in {"line", "summary"} else requested_chart_type,
                    "title": f"Distribucion de {field_label} en {layer_label}",
                    "layer_name": layer_label,
                    "layer": layer_label,
                    "field_used": field,
                    "field_label": field_label,
                    "field_changed": bool(field_metadata.get("field_changed")),
                    "original_field_requested": original_field,
                    "label": field_label,
                    "subtitle": f"Analisis basado en {total} registros consolidados.",
                    "insight": insight,
                    "insight_type": insight_type,
                    "data": data,
                    "categories": data,
                    "all_categories": all_categories,
                    "keys": ["value"],
                    "total_records": total,
                    "total_in_chart": visible_total,
                    "display_limit": max_chart_categories,
                    "grouped_others": bool(other_value > 0),
                    "has_others": bool(other_value > 0),
                    "others_total": other_value,
                    "others_count": max(0, total - visible_total),
                    "warnings": field_metadata.get("warnings", []),
                    "report_available": True,
                }

            return response
        except Exception as exc:
            logger.error("Error en consultar_estadisticas_capa: %s", exc)
            return {"success": False, "error": str(exc)}
