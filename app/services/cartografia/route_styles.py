"""Route styling helpers for cartographic line features."""

from __future__ import annotations

from typing import Any

ROUTE_PALETTE = (
    "#22C55E",
    "#38BDF8",
    "#F97316",
    "#A78BFA",
    "#EC4899",
    "#84CC16",
    "#F59E0B",
    "#06B6D4",
    "#6366F1",
    "#EF4444",
    "#14B8A6",
    "#EAB308",
)


def route_style(properties: dict[str, Any]) -> tuple[str | None, str | None]:
    route_keys = {"sentido", "cod_ruta", "ruta", "tipo", "name", "descripcio"}
    if not route_keys.intersection({str(key).lower() for key in properties.keys()}):
        return None, None

    color = route_color(properties)
    raw_value = str(properties.get("sentido") or properties.get("SENTIDO") or "").strip().upper()
    if not raw_value:
        return None, color
    if any(term in raw_value for term in ("DOBLE", "BIDIRECCIONAL", "AMBOS", "DOS")):
        return "double", color
    if "VUELTA" in raw_value or "RETORNO" in raw_value:
        return "single", color
    if "IDA" in raw_value:
        return "single", color
    if any(term in raw_value for term in ("UNICO", "UNICA", "ONE", "SENCILLO")):
        return "single", color
    return None, color


def route_color(properties: dict[str, Any]) -> str | None:
    raw_key = (
        properties.get("cod_ruta")
        or properties.get("COD_RUTA")
        or properties.get("ruta")
        or properties.get("RUTA")
        or properties.get("name")
        or properties.get("NAME")
        or properties.get("descripcio")
    )
    key = str(raw_key or "").strip()
    if not key:
        return None
    index = sum(ord(char) for char in key) % len(ROUTE_PALETTE)
    return ROUTE_PALETTE[index]
