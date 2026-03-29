"""Servicio geoespacial avanzado para GeoMaps Backend.
Provee funciones asíncronas para manipulación de geometrías Shapely y PostGIS.
"""

import logging
from typing import Any, Sequence
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from app.core.exceptions import GeoProcessingError

logger = logging.getLogger(__name__)


class GeoService:
    """Orquestador de procesos GIS vectoriales."""

    @staticmethod
    async def process_geojson(
        geojson_data: dict[str, Any], 
        epsg_source: int = 4326, 
        epsg_target: int = 4326
    ) -> list[dict[str, Any]]:
        """Transforma datos GeoJSON crudos en documentos WKT aptos para base de datos."""
        from app.utils.feature_normalizer import detect_display_name

        features = geojson_data.get("features", [])
        if not features:
            raise GeoProcessingError("GeoJSON vacío o inválido")

        gdf = gpd.GeoDataFrame.from_features(features, crs=f"EPSG:{epsg_source}")
        if epsg_source != epsg_target:
            gdf = gdf.to_crs(epsg=epsg_target)

        processed_features = []
        for idx, (_, row) in enumerate(gdf.iterrows()):
            if row.geometry and not row.geometry.is_empty:
                props = row.drop("geometry").to_dict()
                processed_features.append({
                    "display_name": detect_display_name(props, idx),
                    "properties": props,
                    "geom_wkt": row.geometry.wkt
                })

        return processed_features

    @staticmethod
    async def get_geometry_type(geojson_data: dict[str, Any]) -> str:
        """Determina el tipo dominante de geometría en una colección de features."""
        features = geojson_data.get("features", [])
        if not features:
            return "Unknown"

        match features[0].get("geometry", {}).get("type"):
            case "Point" | "MultiPoint": return "POINT"
            case "LineString" | "MultiLineString": return "LINESTRING"
            case "Polygon" | "MultiPolygon": return "POLYGON"
            case _: return "GEOMETRY"

    @staticmethod
    def _safe_union(geoms: Sequence[Any]) -> Any:
        """Ejecuta unión de geometrías descartando las vacías o corruptas."""
        valid_geoms = [g for g in geoms if g and not g.is_empty]
        return unary_union(valid_geoms) if valid_geoms else None

    @classmethod
    async def calculate_bounding_box(cls, geojson_data: dict[str, Any]) -> list[float]:
        """Calcula el marco delimitador (MinLon, MinLat, MaxLon, MaxLat) de un GeoJSON."""
        geoms = [shape(f["geometry"]) for f in geojson_data.get("features", [])]
        merged = cls._safe_union(geoms)
        return list(merged.bounds) if merged else [0, 0, 0, 0]

    @classmethod
    async def calculate_total_area(cls, geojson_data: dict[str, Any]) -> float:
        """Calcula el área total acumulada proyectada (en metros cuadrados por defecto)."""
        gdf = gpd.GeoDataFrame.from_features(geojson_data.get("features", []), crs="EPSG:4326")
        gdf = gdf.to_crs(epsg=3857)
        return float(gdf.geometry.area.sum())
