from app.services.ia.geo_context import normalize_extent_to_bbox
import json
from shapely.geometry import shape


def query_scope(bbox=None, filter_field=None, filter_value=None, zone_geometry=None):
    clauses, params = [], {}
    if zone_geometry is not None:
        if not isinstance(zone_geometry, dict) or zone_geometry.get('type') not in ('Polygon','MultiPolygon'):
            raise ValueError('Selecciona un polígono GeoJSON válido')
        encoded = json.dumps(zone_geometry)
        if len(encoded) > 1000000:
            raise ValueError('El polígono supera el límite de análisis')
        polygon = shape(zone_geometry)
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError('El polígono está vacío o es inválido')
        bbox = list(polygon.bounds)
        params['zone_geometry'] = encoded
        clauses.append(' AND CASE WHEN ST_IsValid(geom) THEN ST_Intersects(geom,ST_SetSRID(ST_GeomFromGeoJSON(:zone_geometry),4326)) ELSE FALSE END')
    normalized = normalize_extent_to_bbox(bbox)
    if normalized:
        params.update(dict(zip(('xmin','ymin','xmax','ymax'), normalized)))
        clauses.append(" AND geom && ST_MakeEnvelope(:xmin,:ymin,:xmax,:ymax,4326) AND CASE WHEN ST_IsValid(geom) THEN ST_Intersects(geom,ST_MakeEnvelope(:xmin,:ymin,:xmax,:ymax,4326)) ELSE FALSE END")
    if (filter_field is None) != (filter_value is None):
        raise ValueError('El filtro requiere campo y valor')
    if filter_field is not None:
        if not isinstance(filter_field, str) or not filter_field or len(filter_field) > 255 or len(str(filter_value)) > 1000:
            raise ValueError('Filtro inválido')
        clauses.append(' AND properties->>:filter_field = :filter_value')
        params.update(filter_field=filter_field, filter_value=str(filter_value))
    return ''.join(clauses), params, normalized
