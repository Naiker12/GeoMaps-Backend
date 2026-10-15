"""Alcance cerrado y verificación de respaldo para retirar proyectos."""

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROJECT_TABLES = (
    "project_assets", "project_lots", "project_models_3d", "project_images",
    "project_admin_settings", "project_financials", "project_map_settings",
    "project_metrics", "project_locations", "projects",
)
DEDICATED_BUCKETS = frozenset({"project", "Imagen3d"})


def rows_digest(rows):
    serialized = sorted(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) for row in rows)
    return hashlib.sha256("\n".join(serialized).encode()).hexdigest()


def storage_references(value):
    references = set()
    if isinstance(value, dict):
        if value.get("storage_bucket") and value.get("storage_path"):
            references.add((value["storage_bucket"], value["storage_path"]))
        for child in value.values():
            references.update(storage_references(child))
    elif isinstance(value, list):
        for child in value:
            references.update(storage_references(child))
    elif isinstance(value, str):
        path = unquote(urlsplit(value).path)
        for marker in ("/storage/v1/object/public/", "/storage/v1/object/sign/",
                       "/storage/v1/object/authenticated/", "/storage/v1/render/image/public/"):
            if marker in path:
                suffix = path.split(marker, 1)[1]
                if "/" in suffix:
                    references.add(tuple(suffix.split("/", 1)))
    return references


def select_storage_objects(objects, project_rows, active_references):
    owned = storage_references(project_rows)
    selected, shared = [], []
    for obj in objects:
        key = (obj["bucket_id"], obj["name"])
        if key not in owned and obj["bucket_id"] not in DEDICATED_BUCKETS:
            continue
        if key in active_references:
            shared.append(obj)
        else:
            selected.append(obj)
    if shared:
        raise RuntimeError("Hay archivos de proyectos compartidos con datos activos; no se puede retirar el módulo automáticamente")
    return selected


def verified_backup(path):
    manifest_path = Path(path).resolve()
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "geomaps-project-retirement-v1" or set(manifest.get("table_digests", {})) != set(PROJECT_TABLES):
        raise RuntimeError("El respaldo de proyectos no contiene el alcance completo")
    files = manifest.get("files", [])
    if not any(item["path"] == "restore.sql" for item in files) or not any(item["path"] == "tables.json" for item in files):
        raise RuntimeError("Falta el respaldo de esquema o datos")
    file_paths = {item["path"] for item in files}
    if any(obj.get("backup_file") not in file_paths for obj in manifest.get("objects", [])):
        raise RuntimeError("Falta el respaldo de un archivo de Storage")
    for item in files:
        target = (root / item["path"]).resolve()
        if not target.is_relative_to(root) or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("El respaldo no coincide con sus hashes verificados")
    rows = json.loads((root / "tables.json").read_text(encoding="utf-8"))
    for name in PROJECT_TABLES:
        if rows_digest(rows[name]) != manifest["table_digests"][name]:
            raise RuntimeError("El respaldo de filas está incompleto")
    return manifest
