"""Contexto geográfico compartido entre chat normal, streaming y herramientas."""

from functools import lru_cache
from typing import Any

from pyproj import Transformer
from app.services.spatial.validation import normalize_bbox


@lru_cache(maxsize=1)
def _web_mercator_transformer() -> Transformer:
    return Transformer.from_crs(3857, 4326, always_xy=True)


def normalize_extent_to_bbox(extent: Any) -> list[float] | None:
    if extent is None or extent == {} or extent == []:
        return None
    if isinstance(extent, (list, tuple)) and len(extent) == 4:
        raw = dict(zip(("xmin", "ymin", "xmax", "ymax"), extent))
    elif isinstance(extent, dict):
        raw = {key: extent.get(key) for key in ("xmin", "ymin", "xmax", "ymax")}
        reference = extent.get("spatialReference") or {}
        if not isinstance(reference, dict):
            raise ValueError("Referencia espacial inválida")
        wkid = reference.get("latestWkid") or reference.get("wkid") or 4326
        if wkid in (3857, 102100, 102113):
            try:
                x1, y1 = float(raw["xmin"]), float(raw["ymin"])
                x2, y2 = float(raw["xmax"]), float(raw["ymax"])
                if not (-20037508.3428 <= x1 <= x2 <= 20037508.3428 and -20037508.3428 <= y1 <= y2 <= 20037508.3428):
                    raise ValueError("Extensión Web Mercator fuera de rango")
                xmin, ymin = _web_mercator_transformer().transform(x1, y1)
                xmax, ymax = _web_mercator_transformer().transform(x2, y2)
                raw = {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}
            except (TypeError, ValueError) as exc:
                raise ValueError("Extensión Web Mercator inválida") from exc
        elif wkid != 4326:
            raise ValueError("Referencia espacial no soportada: usa EPSG:4326 o Web Mercator")
    else:
        raise ValueError("La extensión requiere cuatro coordenadas")
    normalized = normalize_bbox(raw)
    return [normalized[key] for key in ("xmin", "ymin", "xmax", "ymax")]


def resolve_geo_context(context_mapa: dict | None, geo_context: dict | None) -> dict:
    context_mapa = context_mapa or {}
    geo_context = geo_context or {}
    zone = geo_context.get("conversation_zone")
    extent = zone.get("bbox") if isinstance(zone, dict) else None
    if extent is None or extent == {} or extent == []:
        extent = geo_context.get("conversation_extent")
    if extent is None or extent == {} or extent == []:
        extent = context_mapa.get("extent")
    return {
        "bbox": normalize_extent_to_bbox(extent),
        "active_zone": zone,
        "conversation_layers": geo_context.get("conversation_layers") or [],
        "applied_filters": geo_context.get("applied_filters") or [],
    }
