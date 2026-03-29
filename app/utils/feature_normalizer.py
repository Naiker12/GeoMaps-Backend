"""
Normaliza los campos de un GeoJSON feature para extraer un nombre
canónico (display_name) independientemente de la capa de origen.

Resuelve el problema central: cada capa tiene su propio campo de nombre
(puesto, nombre, nombre_est, etc.) y el sistema necesita un campo unificado.
"""

# Campos a revisar en orden de prioridad.
# Se verifica primero el más específico, luego el más genérico.
PRIORITY_NAME_FIELDS = [
    # Campos de votaciones (Cartagena)
    "puesto", "localizaci",
    # Campos de educación
    "nombre_est", "nombre_establecimiento",
    # Campos genéricos de nombre
    "nombre", "name", "NOMBRE", "NAME",
    # Campos de localización
    "localidad", "descripcion", "titulo", "label",
    # Dirección como último recurso
    "direccion", "direction",
]

# Campos que nunca deben usarse como nombre (son IDs o números)
SKIP_AS_NAME = {
    "gid", "id", "fid", "objectid", "objectid_1",
    "dd", "mm", "pp", "zz", "x", "y",
    "latitud", "longitud",
    "gridcode", "shape_area", "shape_leng", "shape_le_1",
}


def detect_display_name(properties: dict, feature_index: int = 0) -> str:
    """
    Extrae el nombre más apropiado de las properties de un feature.
    Si no encuentra ningún campo de nombre, devuelve un fallback legible.

    Args:
        properties: Diccionario de properties del GeoJSON feature
        feature_index: Índice del feature (para generar fallback único)

    Returns:
        String con el nombre más apropiado encontrado
    """
    if not properties:
        return f"Entidad #{feature_index + 1}"

    # Intentar campos de prioridad
    for field in PRIORITY_NAME_FIELDS:
        value = properties.get(field)
        if value and isinstance(value, str) and len(value.strip()) > 2:
            return value.strip()

    # Buscar cualquier campo string que parezca un nombre
    for key, value in properties.items():
        if key.lower() in SKIP_AS_NAME:
            continue
        if isinstance(value, str) and len(value.strip()) > 3:
            # Excluir valores que parecen coordenadas o códigos técnicos
            if not value.replace('.', '').replace('-', '').isnumeric():
                return value.strip()

    # Fallback: usar el gid si existe, o el índice
    gid = properties.get("gid") or properties.get("objectid_1")
    if gid:
        return f"Registro #{gid}"

    return f"Entidad #{feature_index + 1}"


def normalize_feature_for_insert(
    feature: dict,
    layer_id: str,
    feature_index: int = 0
) -> dict:
    """
    Prepara un feature GeoJSON para inserción en layer_features.
    Extrae display_name y estructura los datos para el ORM.

    Args:
        feature: Feature del GeoJSON (con geometry y properties)
        layer_id: UUID de la capa padre
        feature_index: Posición del feature en el archivo (para fallback)

    Returns:
        Diccionario listo para insertar en layer_features
    """
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry")

    if not geometry:
        raise ValueError(f"Feature #{feature_index} no tiene geometría válida")

    return {
        "layer_id": layer_id,
        "display_name": detect_display_name(properties, feature_index),
        "properties": properties,
        "geom": geometry,
    }
