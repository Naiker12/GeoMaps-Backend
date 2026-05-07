from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.search_service import SearchService
from .entity_search import EntitySearchTools
from .layer_stats import LayerStatsTools
from .map_controls import MapControlTools
from .route_tools import RouteTools
from .zone_analysis import ZoneAnalysisTools


class ToolsService(
    EntitySearchTools,
    LayerStatsTools,
    MapControlTools,
    RouteTools,
    ZoneAnalysisTools,
):
    def __init__(self, db: AsyncSession):
        self.db = db
        self.search_service = SearchService(db)

    async def get_tools_metadata(self) -> List[Dict[str, Any]]:
        """Devuelve la definicion de herramientas para el LLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "consultar_datos_tabla",
                    "description": "Obtiene un listado detallado de registros de una capa geografica para mostrar en una tabla.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre exacto de la capa."},
                            "limit": {
                                "type": "integer",
                                "description": "Cantidad de registros a retornar. Maximo permitido: 50.",
                                "default": 10,
                                "maximum": 50,
                            },
                        },
                        "required": ["layer_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "consultar_predios",
                    "description": "Busca informacion detallada de predios o lotes por propietario, direccion o matricula.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Texto de busqueda."},
                            "limit": {
                                "type": "integer",
                                "description": "Maximo de resultados. Maximo permitido: 50.",
                                "default": 10,
                                "maximum": 50,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "analizar_zona_extent",
                    "description": "Calcula conteos rapidos por capa dentro del area visible del mapa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "bbox": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "[min_lng, min_lat, max_lng, max_lat]",
                            }
                        },
                        "required": ["bbox"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "consultar_estadisticas_capa",
                    "description": "Genera datos para graficos agrupando por un campo especifico de una capa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."},
                            "field": {"type": "string", "description": "Atributo para agrupar."},
                            "chart_type": {"type": "string", "enum": ["bar", "pie", "line", "summary"]},
                            "limit": {"type": "integer", "description": "Numero de categorias top a mostrar.", "default": 15},
                        },
                        "required": ["layer_name", "field"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "activate_layer",
                    "description": "Controla la visibilidad de las capas en el mapa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."},
                            "visible": {"type": "boolean", "description": "True para mostrar, False para ocultar."},
                        },
                        "required": ["layer_name", "visible"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "buscar_y_mostrar_entidad",
                    "description": "Localiza, resalta y hace zoom a un elemento especifico de una capa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."},
                            "search_field": {"type": "string", "description": "Campo de busqueda."},
                            "search_value": {"type": "string", "description": "Valor exacto o parcial a buscar."},
                        },
                        "required": ["layer_name", "search_field", "search_value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mostrar_ruta_animada",
                    "description": "Dibuja una ruta con animacion tecnica en el mapa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ruta_id": {"type": "string", "description": "Codigo identificador de la ruta."}
                        },
                        "required": ["ruta_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "zoom_to_location",
                    "description": "Mueve la camara del mapa a coordenadas especificas.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "coordinates": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "Par [longitud, latitud] del punto al que se movera el mapa.",
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            "zoom_level": {
                                "type": "integer",
                                "description": "Nivel de zoom entre 1 y 20.",
                                "default": 15,
                                "minimum": 1,
                                "maximum": 20,
                            },
                        },
                        "required": ["coordinates"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "listar_campos_capa",
                    "description": "Explora que atributos tiene una capa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layer_name": {"type": "string", "description": "Nombre de la capa."}
                        },
                        "required": ["layer_name"],
                    },
                },
            },
        ]


__all__ = ["ToolsService"]
