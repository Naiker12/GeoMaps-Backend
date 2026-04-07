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
                "data": features,
                "count": len(features),
                "map_action": "show_markers" if markers else None,
                "markers": markers,
                "zoom_to": True if markers else False,
                "message": f"Se encontraron {len(features)} resultados."
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

    async def consultar_estadisticas_capa(self, layer_name: str, field: str = "estrato") -> Dict[str, Any]:
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

            return {
                "success": True,
                "layer": layer_name,
                "field": field,
                "total": total,
                "analytics_data": {
                    "type": "bar",
                    "title": f"Distribución de {field.capitalize()} - {layer_name}",
                    "data": data,
                    "keys": ["value"],
                    "label": "Registros"
                },
                "mensaje": f"Se analizaron {total} registros en la capa {layer_name} basados en {field}."
            }
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

    async def consultar_datos_tabla(self, layer_name: str, limit: int = 10) -> Dict[str, Any]:
        """Obtiene un listado de registros (filas) de una capa para mostrar en una tabla."""
        try:
            # Buscar el ID de la capa por nombre
            stmt_layer = text("SELECT id FROM public.layers WHERE name ILIKE :name LIMIT 1")
            res_layer = await self.db.execute(stmt_layer, {"name": f"%{layer_name}%"})
            layer_id = res_layer.scalar()
            
            if not layer_id:
                return {"success": False, "error": f"Capa '{layer_name}' no encontrada."}

            # Consultar registros
            stmt_data = text("""
                SELECT properties 
                FROM layer_features 
                WHERE layer_id = :lid 
                LIMIT :limit
            """)
            result = await self.db.execute(stmt_data, {"lid": layer_id, "limit": limit})
            rows = result.fetchall()
            
            table_data = [row[0] for row in rows]

            return {
                "success": True,
                "layer": layer_name,
                "data": table_data,
                "count": len(table_data),
                "mensaje": f"Se obtuvieron {len(table_data)} registros de la capa {layer_name} para la tabla."
            }
        except Exception as e:
            logger.error(f"Error en consultar_datos_tabla: {e}")
            return {"success": False, "error": str(e)}

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
                            "field": {"type": "string", "description": "Campo a analizar (ej: 'estrato', 'estado', 'tipo').", "default": "estrato"}
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
            }
        ]
