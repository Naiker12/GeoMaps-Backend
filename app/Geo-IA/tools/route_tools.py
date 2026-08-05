import json
import logging
from typing import Any, Dict

from sqlalchemy import text

logger = logging.getLogger(__name__)


class RouteTools:
    async def mostrar_ruta_animada(self, ruta_id: str) -> Dict[str, Any]:
        """Muestra una ruta especifica en el mapa con animacion."""
        try:
            stmt = text("""
                SELECT
                    lf.properties->>'cod_ruta' as codigo,
                    lf.properties->>'name' as nombre,
                    lf.properties->>'tipo' as tipo,
                    ST_AsGeoJSON(lf.geom) as geojson,
                    ST_XMin(ST_Envelope(lf.geom)) as bbox_xmin,
                    ST_YMin(ST_Envelope(lf.geom)) as bbox_ymin,
                    ST_XMax(ST_Envelope(lf.geom)) as bbox_xmax,
                    ST_YMax(ST_Envelope(lf.geom)) as bbox_ymax
                FROM public.layer_features lf
                JOIN public.layers l ON l.id = lf.layer_id
                WHERE l.name ILIKE 'RUTAS'
                  AND (
                    lf.properties->>'cod_ruta' ILIKE :ruta_id
                    OR lf.properties->>'name' ILIKE :ruta_id
                  )
                LIMIT 1
            """)
            result = await self.db.execute(stmt, {"ruta_id": f"%{ruta_id}%"})
            row = result.mappings().one_or_none()

            if not row:
                return {"found": False, "message": f"No se encontro la ruta '{ruta_id}' en la capa RUTAS."}

            geojson = json.loads(row["geojson"])
            bbox = [row["bbox_xmin"], row["bbox_ymin"], row["bbox_xmax"], row["bbox_ymax"]]

            return {
                "found": True,
                "ruta": {
                    "codigo": row["codigo"] or "S/C",
                    "nombre": row["nombre"],
                    "tipo": row["tipo"],
                },
                "map_actions": [
                    {
                        "map_action": "toggle_layer",
                        "layer_name": "RUTAS",
                        "visible": True,
                    },
                    {
                        "map_action": "ANIMATE_ROUTE",
                        "geojson": geojson,
                        "bbox": bbox,
                        "color": [34, 197, 94],
                        "routeColor": [34, 197, 94],
                        "duration_ms": 2500,
                        "lineWidth": 2.5,
                    },
                    {
                        "map_action": "filter_layer",
                        "layer_name": "RUTAS",
                        "filter": f"cod_ruta='{row['codigo']}'",
                    },
                ],
                "mensaje": f"He localizado la ruta {row['nombre']}. Iniciando animacion y filtrando el mapa.",
            }
        except Exception as exc:
            logger.error("Error en mostrar_ruta_animada: %s", exc)
            return {"found": False, "error": str(exc)}
