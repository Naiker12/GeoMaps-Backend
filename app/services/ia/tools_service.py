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
        """Realiza un resumen estadístico detallado por capas de lo que hay en un área específica (bbox)."""
        try:
            xmin, ymin, xmax, ymax = bbox
            # Consulta para obtener el desglose por capas en el área
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
            result = await self.db.execute(stmt, {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax})
            rows = result.fetchall()
            
            breakdown = [{"name": row[0], "value": row[1]} for row in rows]
            total_features = sum(d["value"] for d in breakdown)
            total_layers = len(breakdown)
            
            return {
                "success": True,
                "bbox": bbox,
                "data": {
                    "total_elementos": total_features,
                    "capas_afectadas": total_layers,
                    "desglose": breakdown
                },
                "analytics_data": {
                    "type": "table",
                    "title": "Análisis de Cobertura en Zona",
                    "subtitle": f"Se identificaron {total_features} elementos en {total_layers} categorías",
                    "data": breakdown,
                    "columns": [
                        {"key": "name", "label": "Capa"},
                        {"key": "value", "label": "Cantidad"}
                    ],
                    "pdf_export": True
                },
                "mensaje": f"He analizado el área seleccionada y encontré {total_features} elementos distribuidos en {total_layers} capas."
            }
        except Exception as e:
            logger.error(f"Error en analizar_zona_extent: {e}")
            return {"success": False, "error": str(e)}

    async def listar_campos_capa(self, layer_name: str) -> Dict[str, Any]:
        """Obtiene la lista de campos (propiedades) disponibles en una capa para análisis."""
        try:
            stmt = text("SELECT properties FROM layer_features JOIN layers ON layers.id = layer_features.layer_id WHERE unaccent(layers.name) ILIKE unaccent(:name) LIMIT 5")
            result = await self.db.execute(stmt, {"name": f"%{layer_name}%"})
            rows = result.fetchall()
            
            if not rows:
                return {"success": False, "error": f"No se encontraron datos para la capa '{layer_name}'."}
            
            # Unir todas las llaves encontradas en las primeras 5 filas
            all_keys = set()
            for row in rows:
                if row[0]:
                    all_keys.update(row[0].keys())
            
            return {
                "success": True,
                "layer": layer_name,
                "fields": list(all_keys),
                "mensaje": f"La capa '{layer_name}' tiene los siguientes campos disponibles para filtrar o graficar: {', '.join(all_keys)}."
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def consultar_estadisticas_capa(self, layer_name: str, field: str = "estrato", chart_type: str = "bar", include_chart: bool = True, limit: int = 20) -> Dict[str, Any]:
        """Obtiene la distribución de datos (como estratos, categorías) de una capa específica."""
        try:
            # Buscar el ID de la capa por nombre omitiendo acentos
            stmt_layer = text("SELECT id FROM public.layers WHERE unaccent(name) ILIKE unaccent(:name) LIMIT 1")
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
                LIMIT :limit
            """)
            result = await self.db.execute(stmt_stats, {"field": field, "lid": layer_id, "limit": limit})
            rows = result.fetchall()
            
            data = [{"name": str(row[0] or "N/A"), "value": row[1]} for row in rows]
            total = sum(d["value"] for d in data)

            res = {
                "success": True,
                "layer": layer_name,
                "field": field,
                "total": total,
                "data": data, # Mandar siempre los datos crudos para que la IA haga su tabla
                "mensaje": f"Se analizaron {total} registros en la capa {layer_name} basados en {field} (Top {len(data)} resultados)."
            }

            res["analytics_data"] = {
                "type": chart_type,
                "title": f"Distribución de {field.replace('_', ' ').capitalize()}",
                "layer_name": layer_name,
                "label": field.replace('_', ' ').capitalize(),
                "subtitle": f"{total} registros analizados en {len(data)} categorías",
                "insight": f"El valor frecuente es {data[0]['name'] if data else 'N/A'} con {data[0]['value'] if data else 0} registros.",
                "data": data,
                "keys": ["value"],
                "pdf_export": True 
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
                WHERE unaccent(l.name) ILIKE unaccent(:layer) AND unaccent(lf.properties->>:field) ILIKE unaccent(:value)
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
            stmt_layer = text("SELECT id FROM public.layers WHERE unaccent(name) ILIKE unaccent(:name) LIMIT 1")
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
                    "description": "Obtiene un listado detallado de registros de una capa geográfica para mostrar en una tabla. Úsala cuando el usuario quiera inspeccionar datos específicos o ver una lista de elementos.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre exacto de la capa (ej: 'Parques', 'Barrios')."},
                            "limit": {"type": "integer", "description": "Cantidad de registros a retornar.", "default": 10}
                        },
                        "required": ["layer_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "consultar_predios",
                    "description": "Busca información detallada de predios o lotes por propietario, dirección o matrícula.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Texto de búsqueda (nombre, dirección, etc)."},
                            "limit": {"type": "integer", "description": "Máximo de resultados.", "default": 10}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "analizar_zona_extent",
                    "description": "Calcula estadísticas rápidas (conteo de elementos y capas) del área que el usuario está viendo en el mapa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "bbox": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "[min_lng, min_lat, max_lng, max_lat]"
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
                    "description": "Genera datos para gráficos (barras, pastel, etc) agrupando por un campo específico de una capa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."},
                            "field": {"type": "string", "description": "Atributo para agrupar (ej: 'estrato', 'tipo_uso')."},
                            "chart_type": {"type": "string", "enum": ["bar", "pie", "line", "summary"], "description": "Visualización deseada."},
                            "limit": {"type": "integer", "description": "Número de categorías top a mostrar.", "default": 15}
                        },
                        "required": ["layer_name", "field"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "activate_layer",
                    "description": "Controla la visibilidad de las capas en el mapa. Úsala para prender o apagar capas según la solicitud del usuario.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."},
                            "visible": {"type": "boolean", "description": "True para mostrar, False para ocultar."}
                        },
                        "required": ["layer_name", "visible"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "buscar_y_mostrar_entidad",
                    "description": "Localiza, resalta y hace zoom a un elemento específico de una capa usando un criterio de búsqueda.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."},
                            "search_field": {"type": "string", "description": "Campo de búsqueda (ej: 'id', 'nombre')."},
                            "search_value": {"type": "string", "description": "Valor exacto o parcial a buscar."}
                        },
                        "required": ["layer_name", "search_field", "search_value"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "mostrar_ruta_animada",
                    "description": "Dibuja una ruta con una animación técnica en el mapa. Úsala para recorridos, rutas de transporte o trayectos.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ruta_id": {"type": "string", "description": "Código identificador de la ruta."}
                        },
                        "required": ["ruta_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "listar_campos_capa",
                    "description": "Explora qué atributos tiene una capa. Úsala cuando no estés seguro de qué campos usar para filtrar o graficar.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."}
                        },
                        "required": ["layer_name"]
                    }
                }
            }
        ]
