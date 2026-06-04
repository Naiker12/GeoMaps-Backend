"""Project asset classification and storage configuration."""

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MODEL_EXTENSIONS = {".glb", ".gltf", ".obj", ".fbx"}
BIM_EXTENSIONS = {".ifc"}
PDF_EXTENSIONS = {".pdf"}
CAD_EXTENSIONS = {".dxf", ".dwg"}
SPATIAL_EXTENSIONS = {".zip", ".geojson", ".json", ".shp"}

ASSET_KIND_BUCKET = {
    "image": "Imagen",
    "thumbnail": "Imagen",
    "model_3d": "Imagen3d",
    "bim_ifc": "project",
    "document_pdf": "project",
    "cad_dxf": "project",
    "spatial_source": "project",
}

SIGNED_URL_EXPIRES_IN_SECONDS = 60 * 60

ASSET_KIND_FOLDER = {
    "image": "images",
    "thumbnail": "covers",
    "model_3d": "models",
    "bim_ifc": "sources",
    "document_pdf": "documents",
    "cad_dxf": "cad",
    "spatial_source": "spatial",
}

DEFAULT_ROLE_BY_KIND = {
    "image": "gallery",
    "thumbnail": "cover",
    "model_3d": "renderable",
    "bim_ifc": "source",
    "document_pdf": "brochure",
    "cad_dxf": "technical",
    "spatial_source": "source",
}


def classify_asset_by_extension(extension: str) -> str:
    ext = extension.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in MODEL_EXTENSIONS:
        return "model_3d"
    if ext in BIM_EXTENSIONS:
        return "bim_ifc"
    if ext in PDF_EXTENSIONS:
        return "document_pdf"
    if ext in CAD_EXTENSIONS:
        return "cad_dxf"
    if ext in SPATIAL_EXTENSIONS:
        return "spatial_source"
    raise ValueError(f"Extension no soportada: {extension or 'sin extension'}")


def resolve_asset_bucket(kind: str) -> str:
    if kind not in ASSET_KIND_BUCKET:
        raise ValueError(f"Tipo de asset no soportado: {kind}")
    return ASSET_KIND_BUCKET[kind]


def file_extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return f".{filename.rsplit('.', 1)[-1].lower()}"
