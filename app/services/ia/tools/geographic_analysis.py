"""Análisis geográfico medido por PostGIS, con alcance y calidad explícitos."""

import math
import unicodedata
import uuid
import json

from shapely.geometry import shape
from shapely.errors import ShapelyError

from sqlalchemy import text
from app.services.ia.geo_context import normalize_extent_to_bbox
from app.services.spatial.validation import normalize_bbox


def _normalized_name(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(char))


class GeographicAnalysisTools:
    async def analizar_capa_geografica(self, layer_name: str, bbox: list[float] | None = None,
                                      coordinates: list[float] | None = None, radius_m: float | None = None,
                                      scope: str = "current_area", layer_id: str | None = None,
                                      zone_geometry: dict | None = None) -> dict:
        if not isinstance(layer_name, str) or not layer_name.strip() or len(layer_name) > 255:
            raise ValueError("Indica el nombre de una capa")
        bbox = normalize_extent_to_bbox(bbox)
        if scope not in ("current_area", "entire_layer"):
            raise ValueError("Alcance de análisis inválido")
        if scope == "entire_layer" and (bbox is not None or coordinates is not None or zone_geometry is not None):
            raise ValueError("Toda la capa no puede combinarse con filtros de área o proximidad")
        zone_json = None
        if zone_geometry is not None:
            try:
                if not isinstance(zone_geometry, dict):
                    raise ValueError("Geometría de zona inválida")
                if zone_geometry.get("type") == "Feature":
                    zone_geometry = zone_geometry.get("geometry")
                if not isinstance(zone_geometry, dict) or zone_geometry.get("type") not in ("Polygon", "MultiPolygon") or zone_geometry.get("crs"):
                    raise ValueError("Usa un polígono GeoJSON en EPSG:4326")
                zone_json = json.dumps(zone_geometry)
                if len(zone_json) > 1_000_000:
                    raise ValueError("La geometría de zona supera el límite de análisis")
                polygon = shape(zone_geometry)
                if polygon.is_empty or not polygon.is_valid:
                    raise ValueError("El polígono de zona está vacío o es inválido")
                normalize_bbox(dict(zip(("xmin", "ymin", "xmax", "ymax"), polygon.bounds)))
            except (ShapelyError, ValueError, TypeError, KeyError, IndexError) as exc:
                raise ValueError("Selecciona un polígono válido en EPSG:4326 para analizar la zona") from exc
        if (coordinates is None) != (radius_m is None):
            raise ValueError("La proximidad requiere coordenadas y radio en metros")
        if coordinates is not None:
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
                raise ValueError("Usa coordenadas [longitud, latitud]")
            lon, lat = map(float, coordinates)
            radius_m = float(radius_m)
            if not all(math.isfinite(value) for value in (lon, lat, radius_m)) or not (-180 <= lon <= 180 and -90 <= lat <= 90 and 1 <= radius_m <= 50000):
                raise ValueError("Coordenadas o radio inválidos; el radio debe estar entre 1 y 50000 metros")

        name = layer_name.strip()
        escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        selection_params = {"pattern": f"%{escaped}%", "name": name}
        id_clause = ""
        if layer_id is not None:
            selection_params["requested_layer_id"] = uuid.UUID(str(layer_id))
            id_clause = " AND id = :requested_layer_id"
        layers = (await self.db.execute(text("""
            SELECT id, name FROM layers
            WHERE visibility = 'PUBLIC' AND unaccent(name) ILIKE unaccent(:pattern)
            """ + id_clause + """
            ORDER BY (lower(unaccent(name)) = lower(unaccent(:name))) DESC, name, id
            LIMIT 11
        """), selection_params)).mappings().all()
        exact = [layer for layer in layers if _normalized_name(layer["name"]) == _normalized_name(name)]
        matches = exact or layers
        if not matches:
            return {"success": False, "error": "No se encontró una capa disponible con ese nombre"}
        if len(matches) != 1:
            return {"success": False, "needs_clarification": True,
                    "error": "Hay varias capas posibles; elige una capa inequívoca",
                    "candidates": [{"id": str(layer["id"]), "name": layer["name"]} for layer in matches[:10]]}
        layer = matches[0]
        params = {"layer_id": layer["id"]}
        clauses = ["layer_id = :layer_id"]
        if bbox is not None:
            params.update(dict(zip(("xmin", "ymin", "xmax", "ymax"), bbox)))
            clauses.append("geom && ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)")
            clauses.append("ST_Intersects(geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))")
        if coordinates is not None:
            params.update(lon=lon, lat=lat, radius_m=radius_m)
            clauses.append("ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius_m)")
        if zone_json is not None:
            params["zone_geometry"] = zone_json
            clauses.append("ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(:zone_geometry), 4326))")
        # MATERIALIZED evita que el plan aplique predicados exactos a geometrías inválidas.
        candidate_clause = " AND geom && ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)" if bbox is not None else ""
        if zone_json is not None:
            candidate_clause += " AND geom && ST_Envelope(ST_SetSRID(ST_GeomFromGeoJSON(:zone_geometry), 4326))"
        statement = text("""
            WITH usable AS MATERIALIZED (
                SELECT * FROM layer_features
                WHERE layer_id = :layer_id """ + candidate_clause + """ AND geom IS NOT NULL AND ST_IsValid(geom)
                  AND ST_SRID(geom) = 4326
                  AND ST_XMin(geom) >= -180 AND ST_XMax(geom) <= 180
                  AND ST_YMin(geom) >= -90 AND ST_YMax(geom) <= 90
            )
            SELECT ST_GeometryType(geom) AS geometry_type, COUNT(*) AS count,
                SUM(CASE WHEN ST_GeometryType(geom) IN ('ST_Polygon', 'ST_MultiPolygon')
                    THEN ST_Area(geom::geography) ELSE 0 END) AS area_m2
            FROM usable WHERE """ + " AND ".join(clauses) + " GROUP BY ST_GeometryType(geom) ORDER BY count DESC, geometry_type")
        rows = (await self.db.execute(statement, params)).mappings().all()
        types = [{"name": row["geometry_type"].removeprefix("ST_"), "value": int(row["count"])} for row in rows]
        total = sum(item["value"] for item in types)
        scope = "bbox_and_radius" if bbox is not None and coordinates is not None else "bbox" if bbox is not None else "radius" if coordinates is not None else "entire_layer"
        if zone_json is not None:
            scope = "zone_polygon_and_radius" if coordinates is not None else "zone_polygon"
        analysis = {
            "source": "PostGIS", "layer_id": str(layer["id"]), "layer_name": layer["name"],
            "scope": scope, "bbox": bbox, "coordinates": coordinates, "radius_m": radius_m,
            "crs": "EPSG:4326", "count_is_complete": True,
            "zone_geometry_type": zone_geometry.get("type") if zone_json is not None else None,
            "geometry_policy": "valid_non_null_wgs84_only", "total_features": total,
            "sum_feature_area_m2": float(sum(row["area_m2"] or 0 for row in rows)),
            "warnings": ["Se excluyen geometrías nulas, inválidas o fuera de rango.",
                         "El área suma polígonos completos: no recorta al área consultada ni elimina solapamientos."],
        }
        if scope == "entire_layer" and bbox is None and coordinates is None:
            analysis["warnings"].append("El alcance es la capa completa, no una zona administrativa.")
        return {"success": True, "analysis": analysis, "data": {"total_features": total, "geometry_types": types},
                "analytics_data": {"type": "bar", "title": f"Geometrías: {layer['name']}", "data": types,
                    "total_records": total, "warnings": analysis["warnings"], "analysis": analysis} if types else None,
                "mensaje": f"Se encontraron {total} elementos válidos en el alcance {scope}."}
