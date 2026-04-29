import json
import logging
from typing import Any, Dict, List

from sqlalchemy import text

logger = logging.getLogger(__name__)


class EntitySearchTools:
    async def consultar_predios(self, query: str, bbox: List[float] = None, limit: int = 20) -> Dict[str, Any]:
        """Busca predios en la base de datos catastral."""
        try:
            results = await self.search_service.search(query)
            features = results.get("features", [])[:limit]
            markers = []

            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                if geom and geom.get("type") == "Point":
                    coords = geom.get("coordinates", [0, 0])
                    markers.append({
                        "lat": coords[1],
                        "lng": coords[0],
                        "label": props.get("matricula") or props.get("id"),
                        "popup": f"Propietario: {props.get('propietario', 'N/A')}<br>Area: {props.get('area_m2', '0')} m2",
                    })

            table_data = [feature.get("properties", {}) for feature in features]
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
                    "title": f"Resultados de Busqueda: {query}",
                    "data": table_data,
                    "pdf_export": True,
                },
                "mensaje": f"Se encontraron {len(features)} resultados para la busqueda '{query}'.",
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
        """Busca una entidad especifica en una capa y genera acciones de mapa."""
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
                    "message": f"No encontre '{search_value}' en el campo {search_field} de la capa {layer_name}",
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
            stmt_layer = text("SELECT id FROM public.layers WHERE unaccent(name) ILIKE unaccent(:name) LIMIT 1")
            res_layer = await self.db.execute(stmt_layer, {"name": f"%{layer_name}%"})
            layer_id = res_layer.scalar()

            if not layer_id:
                return {"success": False, "error": f"Capa '{layer_name}' no encontrada."}

            stmt_data = text("""
                SELECT properties, ST_AsGeoJSON(ST_Centroid(geom)) as centroid
                FROM layer_features
                WHERE layer_id = :lid
                LIMIT :limit
            """)
            result = await self.db.execute(stmt_data, {"lid": layer_id, "limit": limit})
            rows = result.fetchall()

            table_data = []
            markers = []

            for row in rows:
                props = row[0]
                table_data.append(props)

                if row[1]:
                    try:
                        geom = json.loads(row[1])
                        coords = geom.get("coordinates", [0, 0])
                        markers.append({
                            "lat": coords[1],
                            "lng": coords[0],
                            "label": str(props.get("nombre") or props.get("id") or "Registro"),
                            "popup": f"Capa: {layer_name}",
                        })
                    except (TypeError, ValueError, KeyError, IndexError):
                        continue

            return {
                "success": True,
                "layer": layer_name,
                "data": table_data,
                "count": len(table_data),
                "analytics_data": {
                    "type": "table",
                    "title": f"Detalle de registros: {layer_name}",
                    "layer_name": layer_name,
                    "data": table_data,
                    "pdf_export": True,
                },
                "map_actions": [
                    {
                        "map_action": "show_markers",
                        "markers": markers,
                    }
                ],
                "mensaje": f"Se obtuvieron {len(table_data)} registros de la capa {layer_name}.",
            }
        except Exception as exc:
            logger.error("Error en consultar_datos_tabla: %s", exc)
            return {"success": False, "error": str(exc)}
