import json
import logging
from typing import Any, Dict, List

from sqlalchemy import text

logger = logging.getLogger(__name__)

MAX_TABLE_ROWS = 50
MAX_MAP_MARKERS = 25


DISPLAY_NAME_KEYS = [
    "display_name",
    "nombre",
    "name",
    "nombre_est",
    "puesto",
    "descripcion",
    "descripcio",
    "description",
    "sitio",
    "centro",
    "institucion",
    "colegio",
]

CODE_KEYS = [
    "codigo",
    "cod",
    "cod_paradero",
    "cod_parade",
    "cod_ruta",
    "id_paradero",
]


def _clean_display_value(value: Any) -> str:
    if value is None:
        return ""
    text_value = str(value).strip()
    return "" if text_value.lower() in {"", "none", "null", "nan", "registro"} else text_value


def _get_case_insensitive(props: Dict[str, Any], keys: List[str]) -> str:
    lower_props = {str(k).lower(): v for k, v in props.items()}
    for key in keys:
        value = _clean_display_value(lower_props.get(key.lower()))
        if value:
            return value
    return ""


def get_feature_display_name(props: Dict[str, Any]) -> str:
    """Retorna una etiqueta humana para marcadores de mapa en lugar del genérico 'Registro'."""
    if not props:
        return "Registro"

    direct_name = _get_case_insensitive(props, DISPLAY_NAME_KEYS)
    code = _get_case_insensitive(props, CODE_KEYS)

    if code and direct_name and code.lower() not in direct_name.lower():
        return f"{code} - {direct_name}"
    if direct_name:
        return direct_name
    if code:
        return code

    for key, value in props.items():
        key_lower = str(key).lower()
        if any(token in key_lower for token in ("nombre", "name", "descripcion", "descrip", "codigo", "cod_")):
            cleaned = _clean_display_value(value)
            if cleaned:
                return cleaned

    fallback = _clean_display_value(props.get("id") or props.get("gid") or props.get("objectid"))
    return fallback or "Registro"


def _compact_table_row(props: Dict[str, Any], index: int, value: Any = None) -> Dict[str, Any]:
    label = get_feature_display_name(props)
    return {
        "name": label,
        "label": label,
        "value": value if value is not None else index,
        "properties": props,
    }


class EntitySearchTools:
    async def consultar_predios(self, query: str, bbox: List[float] = None, limit: int = 20) -> Dict[str, Any]:
        """Busca predios en la base de datos catastral."""
        try:
            safe_limit = max(1, min(int(limit or 20), MAX_TABLE_ROWS))
            results = await self.search_service.search(query)
            features = results.get("features", [])[:safe_limit]
            markers = []

            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                if geom and geom.get("type") == "Point" and len(markers) < MAX_MAP_MARKERS:
                    coords = geom.get("coordinates", [0, 0])
                    markers.append({
                        "lat": coords[1],
                        "lng": coords[0],
                        "label": get_feature_display_name(props) or props.get("matricula") or props.get("id"),
                        "popup": f"Propietario: {props.get('propietario', 'N/A')}<br>Area: {props.get('area_m2', '0')} m2",
                        "properties": props,
                    })

            table_data = [
                _compact_table_row(feature.get("properties", {}), index + 1)
                for index, feature in enumerate(features)
            ]
            return {
                "success": True,
                "data": table_data,
                "count": len(features),
                "map_actions": [
                    {
                        "map_action": "show_markers",
                        "markers": markers,
                        "zoom_to": True,
                    }
                ],
                "analytics_data": {
                    "type": "table",
                    "title": f"Resultados de Búsqueda: {query}",
                    "label": "Registro",
                    "data": table_data,
                    "total_records": len(table_data),
                    "display_limit": safe_limit,
                    "report_available": True,
                },
                "mensaje": f"Se encontraron {len(features)} resultados para la búsqueda '{query}'.",
            }
        except Exception as exc:
            logger.error("Error en consultar_predios: %s", exc)
            return {"success": False, "error": str(exc)}

    async def buscar_y_mostrar_entidad(
        self,
        layer_name: str,
        search_field: str,
        search_value: str,
        zoom_to: bool = True,
    ) -> Dict[str, Any]:
        """Busca una entidad específica en una capa y genera acciones de mapa."""
        try:
            stmt = text("""
                SELECT lf.id, ST_AsGeoJSON(lf.geom) as geom, lf.properties
                FROM layer_features lf
                JOIN layers l ON l.id = lf.layer_id
                WHERE unaccent(l.name) ILIKE unaccent(:layer)
                  AND unaccent(lf.properties->>:field) ILIKE unaccent(:value)
                LIMIT 1
            """)
            result = await self.db.execute(
                stmt,
                {"layer": f"%{layer_name}%", "field": search_field, "value": f"%{search_value}%"},
            )
            entity = result.mappings().one_or_none()

            if not entity:
                return {
                    "found": False,
                    "message": f"No encontré '{search_value}' en el campo {search_field} de la capa {layer_name}",
                }

            map_actions = [
                {"map_action": "toggle_layer", "layer_name": layer_name, "visible": True},
                {"map_action": "filter_layer", "layer_name": layer_name, "filter": f"{search_field}='{search_value}'"},
            ]

            return {
                "found": True,
                "entity": entity["properties"],
                "map_actions": map_actions,
            }
        except Exception as exc:
            logger.error("Error en buscar_y_mostrar_entidad: %s", exc)
            return {"found": False, "error": str(exc)}

    async def consultar_datos_tabla(self, layer_name: str, limit: int = 10) -> Dict[str, Any]:
        """Obtiene un listado de registros de una capa para mostrar en tabla."""
        try:
            safe_limit = max(1, min(int(limit or 10), MAX_TABLE_ROWS))
            stmt_layer = text("SELECT id FROM public.layers WHERE unaccent(name) ILIKE unaccent(:name) LIMIT 1")
            res_layer = await self.db.execute(stmt_layer, {"name": f"%{layer_name}%"})
            layer_id = res_layer.scalar()

            if not layer_id:
                return {"success": False, "error": f"Capa '{layer_name}' no encontrada."}

            stmt_count = text("SELECT COUNT(*) FROM layer_features WHERE layer_id = :lid")
            total_records = int((await self.db.execute(stmt_count, {"lid": layer_id})).scalar() or 0)

            stmt_data = text("""
                SELECT properties, ST_AsGeoJSON(ST_Centroid(geom)) as centroid
                FROM layer_features
                WHERE layer_id = :lid
                LIMIT :limit
            """)
            result = await self.db.execute(stmt_data, {"lid": layer_id, "limit": safe_limit})
            rows = result.fetchall()

            table_data = []
            markers = []
            available_fields = set()
            sample_values = {}

            for row in rows:
                props = row[0] or {}
                available_fields.update(str(key) for key in props.keys())
                if not sample_values:
                    sample_values = {str(key): value for key, value in props.items() if value not in (None, "")}
                
                # Para listado de tabla, usamos el índice como valor visual pero tipo tabla
                table_data.append(_compact_table_row(props, len(table_data) + 1))

                if row[1] and len(markers) < MAX_MAP_MARKERS:
                    try:
                        geom = json.loads(row[1])
                        coords = geom.get("coordinates", [0, 0])
                        markers.append({
                            "lat": coords[1],
                            "lng": coords[0],
                            "label": get_feature_display_name(props),
                            "popup": f"Capa: {layer_name}",
                            "properties": props,
                        })
                    except (TypeError, ValueError, KeyError, IndexError):
                        continue

            return {
                "success": True,
                "layer": layer_name,
                "data": table_data,
                "count": len(table_data),
                "total_records": total_records,
                "available_fields": sorted(available_fields),
                "sample_values": sample_values,
                "analytics_data": {
                    "type": "table",
                    "title": f"Listado de {layer_name}",
                    "layer_name": layer_name,
                    "label": "Registro",
                    "data": table_data,
                    "total_records": total_records,
                    "display_limit": safe_limit,
                    # Eliminamos dominant_participation ficticia para datos de listado
                    "report_available": True,
                },
                "map_actions": [
                    {
                        "map_action": "show_markers",
                        "markers": markers,
                    }
                ],
                "mensaje": f"Se muestran {len(table_data)} registros de un total de {total_records} en la capa {layer_name}.",
            }
        except Exception as exc:
            logger.error("Error en consultar_datos_tabla: %s", exc)
            return {"success": False, "error": str(exc)}

