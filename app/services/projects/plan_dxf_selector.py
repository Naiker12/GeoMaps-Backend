"""Selects the best plan DXF asset for footprint generation."""

from __future__ import annotations

from typing import Any

PLAN_TOKENS = ("plan", "planta", "floorplan", "floor", "footprint", "site", "layout")
ELEVATION_TOKENS = (
    "elevation",
    "elevations",
    "elevacion",
    "elevaciones",
    "facade",
    "fachada",
    "section",
    "sections",
    "seccion",
    "secciones",
)


def select_plan_dxf_asset(assets: list[Any]) -> Any | None:
    candidates = [
        asset
        for asset in assets
        if (asset.extension or "").lower() == ".dxf"
        and not is_elevation_asset(asset)
    ]
    if not candidates:
        return None

    return max(candidates, key=plan_asset_score)


def plan_asset_score(asset: Any) -> int:
    text = asset_search_text(asset)
    score = 0
    if asset.role == "plan":
        score += 12
    if any(token in text for token in PLAN_TOKENS):
        score += 8
    if (asset.original_filename or "").lower() == "plan.dxf":
        score += 20
    return score


def is_elevation_asset(asset: Any) -> bool:
    return any(token in asset_search_text(asset) for token in ELEVATION_TOKENS)


def asset_search_text(asset: Any) -> str:
    metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
    return " ".join(
        str(value or "")
        for value in [
            asset.original_filename,
            asset.role,
            metadata.get("label"),
            metadata.get("type"),
        ]
    ).lower()
