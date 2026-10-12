"""Validación de extensiones y límites para consultas espaciales."""

import math


def normalize_bbox(bbox: dict | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    try:
        result = {key: float(bbox[key]) for key in ("xmin", "ymin", "xmax", "ymax")}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("El bbox requiere xmin, ymin, xmax y ymax numéricos") from exc
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("El bbox debe contener coordenadas finitas")
    if not (-180 <= result["xmin"] <= result["xmax"] <= 180 and -90 <= result["ymin"] <= result["ymax"] <= 90):
        raise ValueError("El bbox debe estar ordenado y dentro de EPSG:4326")
    return result


def validate_query_limit(limit: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("El límite de consulta debe ser un entero entre 1 y 500")
