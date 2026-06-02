"""Basemap drawing helpers for cartography exports."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)

ARCGIS_SERVICES = {
    "satellite": ("World_Imagery", "jpg"),
    "streets": ("World_Street_Map", "jpg"),
    "topo": ("World_Topo_Map", "jpg"),
    "dark": ("Canvas/World_Dark_Gray_Base", "png"),
    "terrain": ("World_Terrain_Base", "jpg"),
    "watercolor": ("World_Topo_Map", "jpg"),
}


async def draw_basemap(ax: Any, plt: Any, map_style: str) -> bool:
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    if xmin == xmax or ymin == ymax:
        draw_context_background(ax, map_style)
        return False

    if map_style == "none":
        draw_context_background(ax, map_style)
        return False

    service_info = ARCGIS_SERVICES.get(map_style, ARCGIS_SERVICES["satellite"])
    service, image_format = service_info
    pixel_width, pixel_height = _axes_pixel_size(ax)
    base_params = {
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": f"{pixel_width},{pixel_height}",
        "transparent": "false",
        "dpi": "160",
        "f": "image",
        "format": image_format,
    }

    try:
        import httpx

        timeout = httpx.Timeout(20.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            url = f"https://services.arcgisonline.com/ArcGIS/rest/services/{service}/MapServer/export"
            response = await client.get(
                url,
                params=base_params,
                headers={"User-Agent": "GeoMaps-Cartografia/1.0"},
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if content_type.startswith("image/"):
                image = plt.imread(BytesIO(response.content), format=image_format)
                ax.imshow(
                    image,
                    extent=[xmin, xmax, ymin, ymax],
                    origin="upper",
                    aspect="auto",
                    zorder=0,
                )
                return True
    except Exception as exc:
        logger.debug("No se pudo cargar basemap %s: %s", map_style, exc)

    draw_context_background(ax, map_style)
    return False


def _axes_pixel_size(ax: Any) -> tuple[int, int]:
    fig = ax.figure
    bbox = ax.get_position()
    width = max(int(fig.get_figwidth() * fig.dpi * bbox.width), 800)
    height = max(int(fig.get_figheight() * fig.dpi * bbox.height), 600)
    return min(width, 2200), min(height, 2200)


def draw_context_background(ax: Any, map_style: str = "satellite") -> None:
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()

    if map_style == "dark":
        base, band = "#111827", "#1F2937"
    elif map_style == "none":
        base, band = "#FFFFFF", "#F8FAFC"
    elif map_style == "terrain":
        base, band = "#E7E5D2", "#D7E4C0"
    elif map_style == "watercolor":
        base, band = "#F3F7FA", "#E7EEF4"
    else:
        base, band = "#F8FAFC", "#EEF2F7"

    ax.set_facecolor(base)
    ax.fill_between([xmin, xmax], ymin, ymax, color=base, zorder=0)
    ax.fill_between(
        [xmin, xmax],
        ymin + (ymax - ymin) * 0.0,
        ymin + (ymax - ymin) * 0.34,
        color=band,
        alpha=0.55,
        zorder=0,
    )
