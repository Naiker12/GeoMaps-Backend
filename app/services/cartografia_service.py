"""Generacion de cartas cartograficas digitales con Python."""

from __future__ import annotations

import json
import logging
import math
import tempfile
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.layer_repository import LayerRepository
from app.schemas.cartografia import CartografiaGenerateRequest

logger = logging.getLogger(__name__)


class CartografiaService:
    def __init__(self, db: AsyncSession):
        self.repository = LayerRepository(db)

    async def build_geojson_payload(self, request: CartografiaGenerateRequest) -> dict[str, Any]:
        layer = await self.repository.get(request.layer_id)
        if not layer:
            raise HTTPException(status_code=404, detail="Capa principal no encontrada")

        geojson = await self.repository.get_features_as_geojson(request.layer_id)
        features = self._filter_features(geojson.get("features", []), request)
        attributes = self._resolve_attributes(features, request.attribute_fields)
        cleaned_features = self._project_attributes(features, attributes)

        secondary_payload = None
        if request.secondary_layer_id:
            secondary_layer = await self.repository.get(request.secondary_layer_id)
            if not secondary_layer:
                raise HTTPException(status_code=404, detail="Segunda capa no encontrada")

            secondary_geojson = await self.repository.get_features_as_geojson(request.secondary_layer_id)
            secondary_features = secondary_geojson.get("features", [])
            secondary_payload = {
                "layer_id": request.secondary_layer_id,
                "layer_name": secondary_layer.name,
                "feature_count": len(secondary_features),
                "geojson": {
                    "type": "FeatureCollection",
                    "features": secondary_features,
                },
            }

        payload = {
            "title": request.title,
            "layer_id": request.layer_id,
            "layer_name": layer.name,
            "feature_count": len(cleaned_features),
            "secondary_layer": secondary_payload,
            "attributes": attributes,
            "filters": {
                "data_scope": request.data_scope,
                "field": request.filter_field,
                "value": request.filter_value,
            },
            "geojson": {
                "type": "FeatureCollection",
                "features": cleaned_features,
            },
        }
        return payload

    async def generate_file(self, request: CartografiaGenerateRequest) -> tuple[str, str, str]:
        payload = await self.build_geojson_payload(request)

        if request.output_format == "geojson":
            path = self._write_geojson(payload)
            return path, "application/geo+json", self._filename(request.title, "geojson")

        path = await self._render_map(payload, request)
        media_type = "application/pdf" if request.output_format == "pdf" else "image/png"
        return path, media_type, self._filename(request.title, request.output_format)

    def _filter_features(
        self,
        features: list[dict[str, Any]],
        request: CartografiaGenerateRequest,
    ) -> list[dict[str, Any]]:
        if request.data_scope != "filtered":
            return features
        if not request.filter_field or request.filter_value in (None, ""):
            return features

        expected = str(request.filter_value).strip()
        exact_matches = [
            feature
            for feature in features
            if str((feature.get("properties") or {}).get(request.filter_field, "")).strip() == expected
        ]
        route_code = self._route_code_from_matches(exact_matches)
        if route_code:
            route_matches = [
                feature
                for feature in features
                if str((feature.get("properties") or {}).get("cod_ruta", "")).strip() == route_code
            ]
            if route_matches:
                return route_matches

        return exact_matches

    def _route_code_from_matches(self, features: list[dict[str, Any]]) -> str | None:
        for feature in features:
            props = feature.get("properties") or {}
            has_route_fields = any(key in props for key in ("sentido", "SENTIDO", "cod_ruta"))
            route_code = str(props.get("cod_ruta", "")).strip()
            if has_route_fields and route_code:
                return route_code
        return None

    def _resolve_attributes(
        self,
        features: list[dict[str, Any]],
        requested_attributes: list[str],
    ) -> list[str]:
        if requested_attributes:
            return requested_attributes

        discovered: list[str] = []
        for feature in features[:25]:
            for key in (feature.get("properties") or {}).keys():
                if key not in discovered:
                    discovered.append(key)
                if len(discovered) >= 12:
                    return discovered
        return discovered

    def _project_attributes(
        self,
        features: list[dict[str, Any]],
        attributes: list[str],
    ) -> list[dict[str, Any]]:
        if not attributes:
            return features

        projected = []
        for feature in features:
            props = feature.get("properties") or {}
            projected.append({
                **feature,
                "properties": {key: props.get(key) for key in attributes if key in props},
            })
        return projected

    def _write_geojson(self, payload: dict[str, Any]) -> str:
        output = tempfile.NamedTemporaryFile(delete=False, suffix=".geojson")
        output.close()
        Path(output.name).write_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return output.name

    async def _render_map(self, payload: dict[str, Any], request: CartografiaGenerateRequest) -> str:
        plt = self._get_pyplot()
        width, height = self._figure_size(request.page_size, request.orientation)
        suffix = ".pdf" if request.output_format == "pdf" else ".png"
        output = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        output.close()

        features = payload["geojson"]["features"]
        secondary_features = (payload.get("secondary_layer") or {}).get("geojson", {}).get("features", [])
        table_rows = self._attribute_rows(features, payload["attributes"])

        table_height = 1.05 if table_rows else 0.18
        fig = plt.figure(figsize=(width, height), dpi=180)
        fig.patch.set_facecolor("white")
        grid = fig.add_gridspec(
            nrows=4,
            ncols=1,
            height_ratios=[0.52, 6.4, table_height, 0.42],
            hspace=0.12,
            left=0.055,
            right=0.965,
            top=0.965,
            bottom=0.055,
        )

        title_ax = fig.add_subplot(grid[0])
        title_ax.axis("off")
        title_ax.text(
            0,
            0.65,
            payload["title"],
            fontsize=15,
            fontweight="bold",
            color="#111827",
            ha="left",
            va="center",
        )
        title_ax.text(
            0,
            0.12,
            self._subtitle(payload),
            fontsize=8,
            color="#475569",
            ha="left",
            va="center",
        )

        ax = fig.add_subplot(grid[1])
        ax.set_facecolor("#F8FAFC")

        self._set_map_extent(ax, [*secondary_features, *features])
        await self._draw_basemap(ax, plt)

        if secondary_features:
            self._draw_features(
                ax,
                secondary_features,
                point_color="#F97316",
                line_color="#F97316",
                polygon_color="#FDBA74",
                polygon_edge="#9A3412",
                alpha=0.18,
                linewidth=0.7,
            )
        self._draw_features(ax, features, alpha=0.2)

        self._draw_north_arrow(ax)
        self._draw_scale_bar(ax)
        ax.grid(True, linestyle="--", linewidth=0.35, color="#FFFFFF", alpha=0.28)
        ax.tick_params(
            axis="both",
            which="both",
            bottom=False,
            left=False,
            labelbottom=False,
            labelleft=False,
        )
        ax.set_aspect("equal", adjustable="box")
        for spine in ax.spines.values():
            spine.set_color("#475569")
            spine.set_linewidth(0.7)

        table_ax = fig.add_subplot(grid[2])
        table_ax.axis("off")
        if table_rows:
            self._draw_attribute_table(table_ax, table_rows)

        footer_ax = fig.add_subplot(grid[3])
        footer_ax.axis("off")
        footer_ax.text(
            0,
            0.55,
            "Fuente: GeoMaps | Sistema de coordenadas: EPSG:4326 | Generado automaticamente",
            fontsize=7.2,
            color="#64748B",
            ha="left",
            va="center",
        )

        fig.savefig(output.name, bbox_inches="tight")
        plt.close(fig)
        return output.name

    async def _draw_basemap(self, ax: Any, plt: Any) -> None:
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        if xmin == xmax or ymin == ymax:
            self._draw_context_background(ax)
            return

        base_params = {
            "bbox": f"{xmin},{ymin},{xmax},{ymax}",
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": "1400,900",
            "transparent": "false",
            "dpi": "160",
            "f": "image",
        }
        services = [
            ("World_Imagery", "jpg"),
            ("World_Topo_Map", "jpg"),
            ("World_Street_Map", "jpg"),
        ]

        try:
            import httpx

            timeout = httpx.Timeout(20.0, connect=8.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                for service, image_format in services:
                    url = f"https://services.arcgisonline.com/ArcGIS/rest/services/{service}/MapServer/export"
                    params = {**base_params, "format": image_format}
                    try:
                        response = await client.get(
                            url,
                            params=params,
                            headers={"User-Agent": "GeoMaps-Cartografia/1.0"},
                        )
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "")
                        if not content_type.startswith("image/"):
                            continue

                        image = plt.imread(BytesIO(response.content), format="jpg")
                        ax.imshow(
                            image,
                            extent=[xmin, xmax, ymin, ymax],
                            origin="upper",
                            aspect="auto",
                            zorder=0,
                        )
                        return
                    except Exception as exc:
                        logger.debug("No se pudo cargar basemap ArcGIS %s: %s", service, exc)
        except Exception as exc:
            logger.debug("No se pudo inicializar el cliente de basemap ArcGIS: %s", exc)

        self._draw_context_background(ax)

    def _draw_context_background(self, ax: Any) -> None:
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        ax.set_facecolor("#E8F1E5")
        ax.fill_between([xmin, xmax], ymin, ymax, color="#E8F1E5", zorder=0)
        ax.fill_between(
            [xmin, xmax],
            ymin + (ymax - ymin) * 0.0,
            ymin + (ymax - ymin) * 0.34,
            color="#D8E9D0",
            alpha=0.55,
            zorder=0,
        )

    def _draw_features(
        self,
        ax: Any,
        features: list[dict[str, Any]],
        *,
        point_color: str = "#65A30D",
        line_color: str = "#2563EB",
        polygon_color: str = "#A3E635",
        polygon_edge: str = "#365314",
        alpha: float = 0.28,
        linewidth: float = 0.9,
    ) -> None:
        try:
            from shapely.geometry import shape
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="Shapely no esta disponible para generar la carta") from exc

        for feature in features:
            geometry = feature.get("geometry")
            if not geometry:
                continue
            properties = feature.get("properties") or {}
            geom = shape(geometry)
            geoms = list(getattr(geom, "geoms", [geom]))
            for item in geoms:
                if item.geom_type == "Point":
                    ax.scatter([item.x], [item.y], s=44, color="white", edgecolors="none", alpha=0.9, zorder=4)
                    ax.scatter([item.x], [item.y], s=24, color=point_color, edgecolors="#1E293B", linewidths=0.55, zorder=5)
                elif item.geom_type in ("LineString", "LinearRing"):
                    self._draw_line(ax, item, line_color, linewidth, properties)
                elif item.geom_type == "Polygon":
                    self._draw_polygon(ax, item, polygon_color, polygon_edge, alpha, linewidth)
                elif item.geom_type == "MultiPoint":
                    for point in item.geoms:
                        ax.scatter([point.x], [point.y], s=44, color="white", edgecolors="none", alpha=0.9, zorder=4)
                        ax.scatter([point.x], [point.y], s=24, color=point_color, edgecolors="#1E293B", linewidths=0.55, zorder=5)
                elif item.geom_type == "MultiLineString":
                    for line in item.geoms:
                        self._draw_line(ax, line, line_color, linewidth, properties)
                elif item.geom_type == "MultiPolygon":
                    for polygon in item.geoms:
                        self._draw_polygon(ax, polygon, polygon_color, polygon_edge, alpha, linewidth)

    def _draw_line(
        self,
        ax: Any,
        line: Any,
        color: str,
        linewidth: float,
        properties: dict[str, Any],
    ) -> None:
        direction, route_color = self._route_style(properties)
        color = route_color or color
        x, y = line.xy
        ax.plot(x, y, color="white", linewidth=linewidth + 2.4, alpha=0.9, zorder=3)
        ax.plot(x, y, color=color, linewidth=linewidth + 0.75, zorder=4)

        if direction == "single":
            self._draw_line_arrows(ax, line, color, reverse=False)
        elif direction == "double":
            self._draw_line_arrows(ax, line, color, reverse=False)
            self._draw_line_arrows(ax, line, color, reverse=True)

    def _route_direction(self, properties: dict[str, Any]) -> str | None:
        direction, _color = self._route_style(properties)
        return direction

    def _route_style(self, properties: dict[str, Any]) -> tuple[str | None, str | None]:
        route_keys = {"sentido", "cod_ruta", "ruta", "tipo", "name", "descripcio"}
        if not route_keys.intersection({str(key).lower() for key in properties.keys()}):
            return None, None

        raw_value = str(properties.get("sentido") or properties.get("SENTIDO") or "").strip().upper()
        if not raw_value:
            return None, None
        if any(term in raw_value for term in ("DOBLE", "BIDIRECCIONAL", "AMBOS", "DOS")):
            return "double", "#7C3AED"
        if "VUELTA" in raw_value or "RETORNO" in raw_value:
            return "single", "#F97316"
        if "IDA" in raw_value:
            return "single", "#2563EB"
        if any(term in raw_value for term in ("UNICO", "UNICA", "ONE", "SENCILLO")):
            return "single", "#2563EB"
        return None, None

    def _draw_line_arrows(self, ax: Any, line: Any, color: str, *, reverse: bool) -> None:
        line_length = getattr(line, "length", 0)
        if line_length <= 0 or getattr(line, "is_empty", False):
            return

        fractions = (0.32, 0.5, 0.68) if line_length > 0.015 else (0.5,)
        delta = min(line_length * 0.035, 0.0012)
        delta = max(delta, line_length * 0.012)

        for fraction in fractions:
            distance = line_length * fraction
            start = line.interpolate(max(distance - delta, 0))
            end = line.interpolate(min(distance + delta, line_length))
            if reverse:
                start, end = end, start
            if not all(math.isfinite(value) for value in (start.x, start.y, end.x, end.y)):
                continue

            self._draw_arrow(ax, start.x, start.y, end.x, end.y, "white", 3.0, 5)
            self._draw_arrow(ax, start.x, start.y, end.x, end.y, color, 1.45, 6)

    def _draw_arrow(
        self,
        ax: Any,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        color: str,
        linewidth: float,
        zorder: int,
    ) -> None:
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops={
                "arrowstyle": "-|>",
                "color": color,
                "linewidth": linewidth,
                "mutation_scale": 11,
                "shrinkA": 0,
                "shrinkB": 0,
            },
            zorder=zorder,
        )

    def _draw_polygon(
        self,
        ax: Any,
        polygon: Any,
        face_color: str,
        edge_color: str,
        alpha: float,
        linewidth: float,
    ) -> None:
        x, y = polygon.exterior.xy
        ax.fill(x, y, color=face_color, alpha=alpha, edgecolor=edge_color, linewidth=linewidth, zorder=2)
        for interior in polygon.interiors:
            xi, yi = interior.xy
            ax.plot(xi, yi, color=edge_color, linewidth=max(linewidth * 0.45, 0.25), zorder=3)

    def _set_map_extent(self, ax: Any, features: list[dict[str, Any]]) -> None:
        try:
            from shapely.geometry import shape
            from shapely.ops import unary_union
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="Shapely no esta disponible para calcular la extension") from exc

        geometries = []
        for feature in features:
            geometry = feature.get("geometry")
            if not geometry:
                continue
            try:
                geom = shape(geometry)
            except Exception:
                continue
            if not geom.is_empty:
                geometries.append(geom)

        if not geometries:
            ax.set_xlim(-75.62, -75.46)
            ax.set_ylim(10.34, 10.46)
            return

        bounds = unary_union(geometries).bounds
        minx, miny, maxx, maxy = bounds
        center_x = (minx + maxx) / 2
        center_y = (miny + maxy) / 2
        span_x = max(maxx - minx, 0.045)
        span_y = max(maxy - miny, 0.035)
        span_x *= 1.28
        span_y *= 1.28

        ax.set_xlim(center_x - span_x / 2, center_x + span_x / 2)
        ax.set_ylim(center_y - span_y / 2, center_y + span_y / 2)

    def _draw_north_arrow(self, ax: Any) -> None:
        ax.annotate(
            "N",
            xy=(0.955, 0.88),
            xytext=(0.955, 0.76),
            xycoords="axes fraction",
            textcoords="axes fraction",
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            color="#0F172A",
            arrowprops={"arrowstyle": "-|>", "color": "#0F172A", "linewidth": 1.1},
            bbox={"boxstyle": "circle,pad=0.24", "fc": "white", "ec": "#CBD5E1", "lw": 0.7},
            zorder=10,
        )

    def _draw_scale_bar(self, ax: Any) -> None:
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        center_lat = (ymin + ymax) / 2
        km_per_degree = 111.32 * max(math.cos(math.radians(center_lat)), 0.1)
        map_width_km = abs(xmax - xmin) * km_per_degree
        if map_width_km <= 0:
            return

        target_km = self._nice_scale_distance(map_width_km / 5)
        bar_degrees = target_km / km_per_degree
        x0 = xmin + (xmax - xmin) * 0.06
        y0 = ymin + (ymax - ymin) * 0.065

        ax.plot([x0, x0 + bar_degrees], [y0, y0], color="#0F172A", linewidth=2.2, solid_capstyle="butt", zorder=8)
        tick = (ymax - ymin) * 0.012
        ax.plot([x0, x0], [y0 - tick, y0 + tick], color="#0F172A", linewidth=1.2, zorder=8)
        ax.plot([x0 + bar_degrees, x0 + bar_degrees], [y0 - tick, y0 + tick], color="#0F172A", linewidth=1.2, zorder=8)
        ax.text(
            x0 + bar_degrees / 2,
            y0 + tick * 2.1,
            f"{target_km:g} km",
            ha="center",
            va="bottom",
            fontsize=7,
            color="#0F172A",
            bbox={"boxstyle": "round,pad=0.18", "fc": "white", "ec": "#CBD5E1", "lw": 0.5, "alpha": 0.88},
            zorder=9,
        )

    def _nice_scale_distance(self, value: float) -> float:
        if value <= 0:
            return 1
        exponent = math.floor(math.log10(value))
        fraction = value / (10 ** exponent)
        if fraction < 1.5:
            nice = 1
        elif fraction < 3.5:
            nice = 2
        elif fraction < 7.5:
            nice = 5
        else:
            nice = 10
        return nice * (10 ** exponent)

    def _subtitle(self, payload: dict[str, Any]) -> str:
        parts = [
            f"Capa: {payload['layer_name']}",
            f"Elementos: {payload['feature_count']}",
        ]
        secondary_layer = payload.get("secondary_layer")
        if secondary_layer:
            parts.append(
                f"Segunda capa: {secondary_layer['layer_name']} ({secondary_layer['feature_count']})"
            )
        parts.append("CRS: EPSG:4326")
        return " | ".join(parts)

    def _attribute_rows(self, features: list[dict[str, Any]], attributes: list[str]) -> list[list[str]]:
        if not features or not attributes:
            return []
        visible_attributes = attributes[:8]
        rows = [visible_attributes]
        for feature in features[:8]:
            props = feature.get("properties") or {}
            rows.append([str(props.get(attr, ""))[:34] for attr in visible_attributes])
        return rows

    def _draw_attribute_table(self, ax_table: Any, rows: list[list[str]]) -> None:
        column_count = max(len(rows[0]), 1)
        table = ax_table.table(
            cellText=rows[1:],
            colLabels=rows[0],
            loc="center",
            cellLoc="left",
            colWidths=[1 / column_count] * column_count,
        )
        table.auto_set_font_size(False)
        table.set_fontsize(6.5 if column_count <= 4 else 5.8)
        table.scale(1, 1.08 if column_count <= 4 else 1.16)
        for (row, _col), cell in table.get_celld().items():
            cell.set_edgecolor("#CBD5E1")
            cell.set_linewidth(0.45)
            if row == 0:
                cell.set_facecolor("#E2E8F0")
                cell.set_text_props(weight="bold", color="#0F172A")
            else:
                cell.set_facecolor("#FFFFFF")

    def _figure_size(self, page_size: str, orientation: str) -> tuple[float, float]:
        sizes = {
            "a4": (8.27, 11.69),
            "letter": (8.5, 11),
            "tabloid": (11, 17),
        }
        width, height = sizes.get(page_size, sizes["a4"])
        return (height, width) if orientation == "landscape" else (width, height)

    def _filename(self, title: str, extension: str) -> str:
        safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in title).strip("-")
        return f"{safe or 'cartografia'}-{uuid.uuid4().hex[:8]}.{extension}"

    def _get_pyplot(self):
        import os

        cache_dir = Path(tempfile.gettempdir()) / "geomaps_matplotlib_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
