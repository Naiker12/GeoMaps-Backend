import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

class ToolsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.search_service = SearchService(db)

    async def consultar_predios(self, query: str, bbox: List[float] = None, limit: int = 20) -> Dict[str, Any]:
        """Busca predios (terrenos, lotes, propiedades) en la base de datos catastral."""
        try:
            # Si hay bbox, se lo pasamos al search_service si lo soporta. 
            # Actualmente search_service.search solo toma texto, pero podemos filtrar resultados.
            results = await self.search_service.search(query)
            
            markers = []
            features = results.get("features", [])[:limit]
            
            for f in features:
                # Extraer propiedades para los marcadores
                props = f.get("properties", {})
                geom = f.get("geometry", {})
                if geom and geom.get("type") == "Point":
                    coords = geom.get("coordinates", [0, 0])
                    markers.append({
                        "lat": coords[1],
                        "lng": coords[0],
                        "label": props.get("matricula") or props.get("id"),
                        "popup": f"Propietario: {props.get('propietario', 'N/A')}<br>Área: {props.get('area_m2', '0')} m²"
                    })

            return {
                "success": True,
                "data": [f.get("properties", {}) for f in features],
                "count": len(features),
                "map_actions": [
                    {
                        "map_action": "show_markers",
                        "markers": markers,
                        "zoom_to": True
                    }
                ],
                "analytics_data": {
                    "type": "table",
                    "title": f"Resultados de Búsqueda: {query}",
                    "data": [f.get("properties", {}) for f in features],
                    "pdf_export": True
                },
                "mensaje": f"Se encontraron {len(features)} resultados para la búsqueda '{query}'."
            }
        except Exception as e:
            logger.error(f"Error en consultar_predios: {e}")
            return {"success": False, "error": str(e)}

    async def analizar_zona_extent(self, bbox: List[float]) -> Dict[str, Any]:
        """Realiza un resumen estadístico de lo que hay en un área específica (bbox)."""
        try:
            xmin, ymin, xmax, ymax = bbox
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
                "success": True,
                "bbox": bbox,
                "data": {
                    "total_elementos": row["total_features"],
                    "capas_afectadas": row["total_layers"],
                },
                "analytics_data": {
                    "type": "summary",
                    "title": "Resumen de Zona",
                    "data": [
                        {"name": "Elementos", "value": row["total_features"]},
                        {"name": "Capas", "value": row["total_layers"]}
                    ]
                },
                "mensaje": f"He analizado el área seleccionada y encontré {row['total_features']} elementos distribuidos en {row['total_layers']} capas."
            }
        except Exception as e:
            logger.error(f"Error en analizar_zona_extent: {e}")
            return {"success": False, "error": str(e)}

    async def consultar_estadisticas_capa(self, layer_name: str, field: str = "estrato", chart_type: str = "bar", include_chart: bool = True) -> Dict[str, Any]:
        """Obtiene la distribución de datos (como estratos, categorías) de una capa específica."""
        try:
            # Buscar el ID de la capa por nombre
            stmt_layer = text("SELECT id FROM public.layers WHERE name ILIKE :name LIMIT 1")
            res_layer = await self.db.execute(stmt_layer, {"name": f"%{layer_name}%"})
            layer_id = res_layer.scalar()
            
            if not layer_id:
                return {"success": False, "error": f"Capita '{layer_name}' no encontrada."}

            # Consultar distribución del campo solicitado
            stmt_stats = text(f"""
                SELECT 
                    properties->>:field as category,
                    count(*) as total
                FROM layer_features
                WHERE layer_id = :lid
                GROUP BY 1
                ORDER BY 2 DESC
                LIMIT 8
            """)
            result = await self.db.execute(stmt_stats, {"field": field, "lid": layer_id})
            rows = result.fetchall()
            
            data = [{"name": str(row[0] or "N/A"), "value": row[1]} for row in rows]
            total = sum(d["value"] for d in data)

            res = {
                "success": True,
                "layer": layer_name,
                "field": field,
                "total": total,
                "data": data, # Mandar siempre los datos crudos para que la IA haga su tabla
                "mensaje": f"Se analizaron {total} registros en la capa {layer_name} basados en {field}."
            }

            res["analytics_data"] = {
                "type": chart_type,
                "title": f"Distribución de {field.capitalize()}",
                "layer_name": layer_name,
                "label": field.capitalize(),
                "subtitle": f"{total} registros analizados",
                "insight": f"El valor principal es {data[0]['name'] if data else 'N/A'} con {data[0]['value'] if data else 0} registros.",
                "data": data,
                "keys": ["value"],
                "pdf_export": True # Habilitar siempre exportación si hay datos analíticos
            }
            
            return res
        except Exception as e:
            logger.error(f"Error en consultar_estadisticas_capa: {e}")
            return {"success": False, "error": str(e)}

    async def activate_layer(self, layer_name: str, visible: bool = True) -> Dict[str, Any]:
        """Activa o desactiva capas del mapa."""
        return {
            "success": True,
            "layer_name": layer_name,
            "visible": visible,
            "map_action": "toggle_layer"
        }

    async def zoom_to_location(self, coordinates: Dict[str, float], zoom_level: int = 15) -> Dict[str, Any]:
        """Mueve el mapa y hace zoom a una ubicación."""
        return {
            "success": True,
            "coordinates": coordinates,
            "zoom_level": zoom_level,
            "map_action": "fly_to"
        }

    async def buscar_y_mostrar_entidad(
        self,
        layer_name: str,
        search_field: str,
        search_value: str,
        zoom_to: bool = True
    ) -> Dict[str, Any]:
        """
        Busca una entidad específica en una capa y la muestra aislada en el mapa.
        """
        try:
            stmt = text("""
                SELECT lf.id, ST_AsGeoJSON(lf.geom) as geom, lf.properties
                FROM layer_features lf
                JOIN layers l ON l.id = lf.layer_id
                WHERE l.name ILIKE :layer AND lf.properties->>:field ILIKE :value
                LIMIT 1
            """)
            result = await self.db.execute(stmt, {"layer": f"%{layer_name}%", "field": search_field, "value": f"%{search_value}%"})
            entity = result.mappings().one_or_none()
            
            if not entity:
                return {"found": False, "message": f"No encontré '{search_value}' en el campo {search_field} de la capa {layer_name}"}

            centroid_stmt = text("""
                SELECT ST_X(ST_Centroid(geom)), ST_Y(ST_Centroid(geom))
                FROM layer_features WHERE id = :id
            """)
            centroid_result = await self.db.execute(centroid_stmt, {"id": entity["id"]})
            centroid = centroid_result.fetchone()
            lng, lat = centroid if centroid else (0, 0)

            return {
                "found": True,
                "entity": entity["properties"],
                "map_actions": [
                    {"type": "toggle_layer", "layer_name": layer_name, "visible": True},
                    {"type": "highlight_feature", "layer_name": layer_name, "feature_id": entity["id"]},
                    {"type": "fly_to", "lat": lat, "lng": lng, "zoom": 15},
                    {"type": "filter_layer", "layer_name": layer_name, "filter": f"{search_field}='{search_value}'"}
                ]
            }
        except Exception as e:
            logger.error(f"Error en buscar_y_mostrar_entidad: {e}")
            return {"found": False, "error": str(e)}

    async def consultar_datos_tabla(self, layer_name: str, limit: int = 10) -> Dict[str, Any]:
        """Obtiene un listado de registros (filas) de una capa para mostrar en una tabla."""
        try:
            # Buscar el ID de la capa por nombre
            stmt_layer = text("SELECT id FROM public.layers WHERE name ILIKE :name LIMIT 1")
            res_layer = await self.db.execute(stmt_layer, {"name": f"%{layer_name}%"})
            layer_id = res_layer.scalar()
            
            if not layer_id:
                return {"success": False, "error": f"Capa '{layer_name}' no encontrada."}

            # Consultar registros con su centroide para mostrar marcadores
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
                
                # Intentar crear marcador si hay centroide
                if row[1]:
                    try:
                        geom = json.loads(row[1])
                        coords = geom.get("coordinates", [0, 0])
                        markers.append({
                            "lat": coords[1],
                            "lng": coords[0],
                            "label": str(props.get("nombre") or props.get("id") or "Registro"),
                            "popup": f"Capa: {layer_name}"
                        })
                    except:
                        pass

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
                    "pdf_export": True
                },
                "map_actions": [
                    {
                        "map_action": "show_markers",
                        "markers": markers
                    }
                ],
                "mensaje": f"Se obtuvieron {len(table_data)} registros de la capa {layer_name}."
            }
        except Exception as e:
            logger.error(f"Error en consultar_datos_tabla: {e}")
            return {"success": False, "error": str(e)}

    async def mostrar_ruta_animada(self, ruta_id: str) -> Dict[str, Any]:
        """Muestra una ruta específica en el mapa con animación progresiva."""
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
                WHERE l.name ILIKE 'RUTAS' AND (lf.properties->>'cod_ruta' ILIKE :ruta_id OR lf.properties->>'name' ILIKE :ruta_id)
                LIMIT 1
            """)
            result = await self.db.execute(stmt, {"ruta_id": f"%{ruta_id}%"})
            row = result.mappings().one_or_none()
            
            if not row:
                return {"found": False, "message": f"No se encontró la ruta '{ruta_id}' en la capa RUTAS."}
            
            geojson = json.loads(row["geojson"])
            bbox = [row["bbox_xmin"], row["bbox_ymin"], row["bbox_xmax"], row["bbox_ymax"]]
            
            return {
                "found": True,
                "ruta": {
                    "codigo": row["codigo"] or "S/C",
                    "nombre": row["nombre"],
                    "tipo": row["tipo"]
                },
                "map_actions": [
                    {
                        "map_action": "toggle_layer",
                        "layer_name": "RUTAS",
                        "visible": True
                    },
                    {
                        "map_action": "ANIMATE_ROUTE",
                        "geojson": geojson,
                        "bbox": bbox,
                        "color": "#4ade80",
                        "duration_ms": 3500
                    },
                    {
                        "map_action": "filter_layer",
                        "layer_name": "RUTAS",
                        "filter": f"cod_ruta='{row['codigo']}'"
                    }
                ],
                "mensaje": f"He localizado la ruta **{row['nombre']}**. Iniciando animación técnica y filtrando mapa para visualización exclusiva."
            }
        except Exception as e:
            logger.error(f"Error en mostrar_ruta_animada: {e}")
            return {"found": False, "error": str(e)}

    async def get_tools_metadata(self) -> List[Dict[str, Any]]:
        """Devuelve la definición de las herramientas para el LLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "consultar_datos_tabla",
                    "description": "Obtiene un listado detallado de registros de una capa para mostrar en una tabla Markdown. Úsala cuando el usuario pida 'ver lista', 'tabla de', 'dame 10 registros', etc.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."},
                            "limit": {"type": "integer", "description": "Número de registros a mostrar.", "default": 10}
                        },
                        "required": ["layer_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "consultar_predios",
                    "description": "Busca predios, lotes o información geográfica relevante.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Nombre o criterio de búsqueda."},
                            "limit": {"type": "integer", "description": "Máximo de resultados.", "default": 20}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "analizar_zona_extent",
                    "description": "Analiza estadísticamente el área visible actual del mapa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "bbox": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "[xmin, ymin, xmax, ymax]"
                            }
                        },
                        "required": ["bbox"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "consultar_estadisticas_capa",
                    "description": "Obtiene estadísticas y distribuciones (estratos, tipos, categorías) de una capa para generar gráficas.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."},
                            "field": {"type": "string", "description": "Campo por el cual agrupar (ej: 'estrato', 'tipo', 'estado')."},
                            "chart_type": {"type": "string", "enum": ["bar", "pie", "line", "summary"], "description": "Tipo de gráfico."},
                            "include_chart": {"type": "boolean", "description": "Si es True, genera un componente gráfico. Úsalo solo si el usuario pide 'graficar' o si la respuesta requiere visualización masiva.", "default": True}
                        },
                        "required": ["layer_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "activate_layer",
                    "description": "Activa o desactiva una capa específica del mapa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa a modificar."},
                            "visible": {"type": "boolean", "description": "True para activar, False para desactivar."}
                        },
                        "required": ["layer_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "buscar_y_mostrar_entidad",
                    "description": "Busca una entidad específica (por código, id, o nombre exacto) y la muestra en el mapa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."},
                            "search_field": {"type": "string", "description": "Campo a buscar (ej: 'codigo', 'nombre')."},
                            "search_value": {"type": "string", "description": "Valor a buscar."},
                            "zoom_to": {"type": "boolean", "description": "Si se debe hacer zoom a la entidad.", "default": True}
                        },
                        "required": ["layer_name", "search_field", "search_value"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "mostrar_ruta_animada",
                    "description": "Muestra una ruta específica en el mapa con animación. Úsala cuando el usuario pida ver, mostrar o trazar una ruta por código (ej: X101) o nombre.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ruta_id": {
                                "type": "string",
                                "description": "Código o ID de la ruta, ej: X101, R-45"
                            }
                        },
                        "required": ["ruta_id"]
                    }
                }
            }
        ]
