"""Helpers to extract territorial scopes from user messages."""

from __future__ import annotations

import re
import unicodedata
from typing import List


COMPARISON_KEYWORDS = (
    "compara",
    "comparar",
    "comparacion",
    "comparación",
    "vs",
    "versus",
    "diferencia",
    "diferencias",
    "contrasta",
    "contrastar",
    "entre",
)

_CONNECTOR_RE = re.compile(r"\s+(?:y|vs\.?|versus|contra|con)\s+|,\s*", re.IGNORECASE)
_STOP_RE = re.compile(
    r"\s+(?:para|en pdf|pdf|reporte|informe|analisis|análisis|genera|generar|datos|estadisticas|estadísticas)\b.*$",
    re.IGNORECASE,
)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", normalized).strip().lower()


def title_zone_name(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip(" .,:;")
    aliases = {
        "pie de la papa": "Pie de la Popa",
        "pie de la poca": "Pie de la Popa",
    }
    normalized = normalize_text(cleaned)
    if normalized in aliases:
        return aliases[normalized]
    return " ".join(part.capitalize() for part in cleaned.split())


def is_comparison_request(message: str) -> bool:
    normalized = normalize_text(message)
    return any(keyword in normalized for keyword in COMPARISON_KEYWORDS)


def extract_zone_names(message: str) -> List[str]:
    """Extract one or more barrio/zona names while preserving order."""
    normalized = normalize_text(message)
    ignored = {
        "actual",
        "visible",
        "esta zona",
        "esta area",
        "capas",
        "datos",
        "la zona visible actual",
        "la vista actual",
    }

    candidates: List[str] = []
    patterns = [
        r"(?:barrios?|zonas?|sectores?|areas?)\s+(?:de\s+|del\s+|la\s+|el\s+)?(.+?)(?=\s+(?:para|en pdf|pdf|reporte|informe|analisis|análisis|genera|generar)|$)",
        r"(?:compara|comparar|comparacion|comparación|contrasta|contrastar|entre)\s+(.+?)(?=\s+(?:para|en pdf|pdf|reporte|informe|analisis|análisis|genera|generar)|$)",
        r"(?:reporte|informe|analisis|análisis)\s+(?:de\s+|del\s+|para\s+)?(?:la\s+zona\s+|el\s+barrio\s+|barrio\s+|sector\s+)?(.+?)(?=\s+(?:para|en pdf|pdf)|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            raw = _STOP_RE.sub("", match.group(1)).strip()
            candidates.extend(part.strip() for part in _CONNECTOR_RE.split(raw))

    zones: List[str] = []
    seen = set()
    for candidate in candidates:
        candidate = candidate.strip(" .,:;")
        if len(candidate) < 3 or candidate in ignored:
            continue
        titled = title_zone_name(candidate)
        key = normalize_text(titled)
        if key not in seen:
            seen.add(key)
            zones.append(titled)

    return zones