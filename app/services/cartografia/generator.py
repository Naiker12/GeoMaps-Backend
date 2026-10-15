"""Generacion de cartas cartograficas digitales con Python."""

from __future__ import annotations

import json
import logging
import math
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.layer_repository import LayerRepository
from app.schemas.cartografia import CartografiaGenerateRequest
from app.services.cartografia.basemap_renderer import draw_basemap
from app.services.cartografia.page_border import draw_border
from app.services.cartografia.payload_builder import CartografiaPayloadBuilder
from app.services.cartografia.route_styles import route_style

logger = logging.getLogger(__name__)

class CartografiaService:
    def __init__(self, db: AsyncSession):
        self.repository = LayerRepository(db)
        self.payload_builder = CartografiaPayloadBuilder(self.repository)

    async def build_geojson_payload(self, request: CartografiaGenerateRequest) -> dict[str, Any]:
        return await self.payload_builder.build(request)

    async def generate_file(self, request: CartografiaGenerateRequest) -> tuple[str, str, str]:
        payload = await self.build_geojson_payload(request)

        if request.output_format == "geojson":
            path = self._write_geojson(payload)
            return path, "application/geo+json", self._filename(request.title, "geojson")

        path = await self._render_map(payload, request)
        media_type = "application/pdf" if request.output_format == "pdf" else "image/png"
        return path, media_type, self._filename(request.title, request.output_format)

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

        if request.output_format == "png":
            fig, ax = self._build_map_only_figure(plt, width, height)
            await self._draw_map_content(ax, plt, features, secondary_features, request, include_decorations=False)
            fig.savefig(output.name, bbox_inches="tight", pad_inches=0.02)
            plt.close(fig)
            return output.name

        separate_attribute_page = request.output_format == "pdf" and request.attributes_on_separate_page
        attribute_table_rows = self._attribute_rows(
            features,
            payload["attributes"],
            max_features=None if separate_attribute_page else 8,
        )
        table_rows = [] if separate_attribute_page else attribute_table_rows

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

        await self._draw_map_content(ax, plt, features, secondary_features, request)

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

        draw_border(fig, request.border_style)

        if separate_attribute_page:
            from matplotlib.backends.backend_pdf import PdfPages

            with PdfPages(output.name) as pdf:
                pdf.savefig(fig)
                plt.close(fig)
                table_pages = self._chunk_attribute_rows(
                    attribute_table_rows,
                    rows_per_page=self._table_rows_per_page(request.page_size, request.orientation),
                )
                for page_index, page_rows in enumerate(table_pages, start=1):
                    table_fig = self._build_attribute_page(
                        plt,
                        payload,
                        request,
                        page_rows,
                        width,
                        height,
                        page_index,
                        len(table_pages),
                    )
                    pdf.savefig(table_fig)
                    plt.close(table_fig)
        else:
            fig.savefig(output.name)
            plt.close(fig)
        return output.name

    def _build_map_only_figure(self, plt: Any, width: float, height: float) -> tuple[Any, Any]:
        fig = plt.figure(figsize=(width, height), dpi=220)
        fig.patch.set_facecolor("white")
        ax = fig.add_axes([0.025, 0.025, 0.95, 0.95])
        ax.set_facecolor("#F8FAFC")
        return fig, ax

    async def _draw_map_content(
        self,
        ax: Any,
        plt: Any,
        features: list[dict[str, Any]],
        secondary_features: list[dict[str, Any]],
        request: CartografiaGenerateRequest,
        include_decorations: bool = True,
    ) -> None:
        self._set_map_extent(ax, [*secondary_features, *features])
        has_basemap = await self._draw_basemap(ax, plt, request.map_style)
        primary_color = self._safe_hex_color(request.primary_color)
        secondary_color = self._safe_hex_color(request.secondary_color)
        primary_edge = self._darken_hex_color(primary_color, 0.58) if primary_color else "#15803D"
        secondary_edge = self._darken_hex_color(secondary_color, 0.58) if secondary_color else "#9A3412"
        show_primary_arrows = self._should_show_route_arrows(features, request)
        polygon_alpha = self._polygon_alpha(has_basemap, include_decorations)
        polygon_linewidth = 0.7 if include_decorations else 1.05

        if secondary_features:
            self._draw_features(
                ax,
                secondary_features,
                point_color=secondary_color or "#F97316",
                line_color=secondary_color or "#F97316",
                polygon_color=secondary_color or "#FDBA74",
                polygon_edge=secondary_edge,
                alpha=max(polygon_alpha * 0.75, 0.12),
                linewidth=0.7,
                use_route_palette=secondary_color is None,
                show_direction_arrows=False,
            )
        self._draw_features(
            ax,
            features,
            point_color=primary_color or "#65A30D",
            line_color=primary_color or "#2563EB",
            polygon_color=primary_color or "#86EFAC",
            polygon_edge=primary_edge,
            alpha=polygon_alpha,
            linewidth=polygon_linewidth,
            use_route_palette=primary_color is None,
            show_direction_arrows=show_primary_arrows,
        )
        self._draw_feature_labels(ax, features, request.label_field)

        if include_decorations:
            self._draw_north_arrow(ax)
            self._draw_scale_bar(ax)
            ax.grid(True, linestyle="--", linewidth=0.25, color="#FFFFFF", alpha=0.14)
        ax.tick_params(
            axis="both",
            which="both",
            bottom=False,
            left=False,
            labelbottom=False,
            labelleft=False,
        )
        ax.set_aspect("auto")
        for spine in ax.spines.values():
            spine.set_color("#475569")
            spine.set_linewidth(0.7)

    def _polygon_alpha(self, has_basemap: bool, include_decorations: bool) -> float:
        if has_basemap:
            return 0.10 if include_decorations else 0.08
        return 0.24 if include_decorations else 0.20

    def _should_show_route_arrows(
        self,
        features: list[dict[str, Any]],
        request: CartografiaGenerateRequest,
    ) -> bool:
        if request.data_scope != "filtered" or len(features) > 80:
            return False

        route_keys: set[str] = set()
        for feature in features:
            properties = feature.get("properties") or {}
            raw_key = (
                properties.get("cod_ruta")
                or properties.get("COD_RUTA")
                or properties.get("ruta")
                or properties.get("RUTA")
                or properties.get("name")
                or properties.get("NAME")
            )
            key = str(raw_key or "").strip()
            if key:
                route_keys.add(key)
            if len(route_keys) > 4:
                return False
        return bool(route_keys)

    def _safe_hex_color(self, color: str | None) -> str | None:
        if not color:
            return None
        value = color.strip()
        if len(value) == 7 and value.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in value[1:]):
            return value
        return None

    def _darken_hex_color(self, color: str | None, factor: float) -> str:
        if not color:
            return "#15803D"
        factor = min(max(factor, 0.0), 1.0)
        red = int(color[1:3], 16)
        green = int(color[3:5], 16)
        blue = int(color[5:7], 16)
        return f"#{int(red * factor):02X}{int(green * factor):02X}{int(blue * factor):02X}"

    def _draw_feature_labels(
        self,
        ax: Any,
        features: list[dict[str, Any]],
        label_field: str | None,
    ) -> None:
        if not label_field or not features:
            return

        try:
            from matplotlib import patheffects
            from shapely.geometry import shape
        except ImportError:
            return

        feature_count = len(features)
        font_size = 6.2
        max_labels = 90
        if feature_count > 160:
            font_size = 3.4
            max_labels = 120
        elif feature_count > 100:
            font_size = 4.0
            max_labels = 95
        elif feature_count > 60:
            font_size = 4.6
            max_labels = 80

        seen_candidates: set[str] = set()
        label_candidates = []
        for feature in features:
            properties = feature.get("properties") or {}
            label = str(properties.get(label_field, "")).strip()
            if not label:
                continue
            normalized = label.upper()
            if normalized in seen_candidates:
                continue
            seen_candidates.add(normalized)

            geometry = feature.get("geometry")
            if not geometry:
                continue
            try:
                geom = shape(geometry)
            except Exception:
                continue
            if geom.is_empty:
                continue

            point = self._label_point(geom)
            if point is None:
                continue
            label_candidates.append((self._label_weight(geom), point, label))

        drawn_count = 0
        for _weight, point, label in sorted(label_candidates, key=lambda item: item[0], reverse=True):
            ax.text(
                point.x,
                point.y,
                self._truncate_label(label),
                ha="center",
                va="center",
                fontsize=font_size,
                color="#1F2937",
                alpha=0.82,
                zorder=9,
                path_effects=[
                    patheffects.withStroke(linewidth=1.65, foreground="white", alpha=0.82),
                ],
                clip_on=True,
            )
            drawn_count += 1
            if drawn_count >= max_labels:
                break

    def _label_point(self, geom: Any) -> Any | None:
        geom_type = getattr(geom, "geom_type", "")
        if geom_type in ("Polygon", "MultiPolygon"):
            return geom.representative_point()
        if geom_type in ("LineString", "LinearRing"):
            return geom.interpolate(0.5, normalized=True)
        if geom_type == "MultiLineString":
            longest = max(list(geom.geoms), key=lambda item: getattr(item, "length", 0), default=None)
            return longest.interpolate(0.5, normalized=True) if longest else None
        if geom_type == "Point":
            return geom
        if geom_type == "MultiPoint":
            return geom.centroid
        return geom.representative_point() if hasattr(geom, "representative_point") else None

    def _label_weight(self, geom: Any) -> float:
        return float(getattr(geom, "area", 0) or getattr(geom, "length", 0) or 1)

    def _truncate_label(self, label: str) -> str:
        value = " ".join(label.split())
        return value if len(value) <= 16 else f"{value[:14]}..."

    def _build_attribute_page(
        self,
        plt: Any,
        payload: dict[str, Any],
        request: CartografiaGenerateRequest,
        table_rows: list[list[str]],
        width: float,
        height: float,
        page_number: int = 1,
        total_pages: int = 1,
    ) -> Any:
        fig = plt.figure(figsize=(width, height), dpi=180)
        fig.patch.set_facecolor("white")
        grid = fig.add_gridspec(
            nrows=3,
            ncols=1,
            height_ratios=[0.8, 7.2, 0.34],
            hspace=0.08,
            left=0.055,
            right=0.965,
            top=0.935,
            bottom=0.045,
        )

        title_ax = fig.add_subplot(grid[0])
        title_ax.axis("off")
        title_ax.text(
            0,
            0.62,
            f"Tabla de atributos - {payload['layer_name']}",
            fontsize=13,
            fontweight="bold",
            color="#111827",
            ha="left",
            va="center",
        )
        title_ax.text(
            0,
            0.14,
            f"{payload['feature_count']} elementos | {len(payload['attributes'])} atributos | Pagina {page_number} de {total_pages}",
            fontsize=8,
            color="#475569",
            ha="left",
            va="center",
        )

        table_ax = fig.add_subplot(grid[1])
        table_ax.axis("off")
        if table_rows and table_rows[0]:
            self._draw_attribute_table(table_ax, table_rows, full_page=True)
        else:
            table_ax.text(
                0.5,
                0.5,
                "No hay atributos seleccionados para mostrar.",
                fontsize=10,
                color="#64748B",
                ha="center",
                va="center",
            )

        footer_ax = fig.add_subplot(grid[2])
        footer_ax.axis("off")
        footer_ax.text(
            0,
            0.55,
            "Fuente: GeoMaps | Sistema de coordenadas: EPSG:4326 | Tabla generada automaticamente",
            fontsize=7.2,
            color="#64748B",
            ha="left",
            va="center",
        )
        draw_border(fig, request.border_style)
        return fig

    async def _draw_basemap(self, ax: Any, plt: Any, map_style: str = "satellite") -> bool:
        return await draw_basemap(ax, plt, map_style)

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
        use_route_palette: bool = True,
        show_direction_arrows: bool = False,
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
                    self._draw_line(
                        ax,
                        item,
                        line_color,
                        linewidth,
                        properties,
                        use_route_palette=use_route_palette,
                        show_direction_arrows=show_direction_arrows,
                    )
                elif item.geom_type == "Polygon":
                    self._draw_polygon(ax, item, polygon_color, polygon_edge, alpha, linewidth)
                elif item.geom_type == "MultiPoint":
                    for point in item.geoms:
                        ax.scatter([point.x], [point.y], s=44, color="white", edgecolors="none", alpha=0.9, zorder=4)
                        ax.scatter([point.x], [point.y], s=24, color=point_color, edgecolors="#1E293B", linewidths=0.55, zorder=5)
                elif item.geom_type == "MultiLineString":
                    for line in item.geoms:
                        self._draw_line(
                            ax,
                            line,
                            line_color,
                            linewidth,
                            properties,
                            use_route_palette=use_route_palette,
                            show_direction_arrows=show_direction_arrows,
                        )
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
        use_route_palette: bool = True,
        show_direction_arrows: bool = False,
    ) -> None:
        direction, route_color = self._route_style(properties)
        if not use_route_palette:
            route_color = None
        color = route_color or color
        x, y = line.xy
        ax.plot(x, y, color="white", linewidth=linewidth + 1.1, alpha=0.55, zorder=3)
        ax.plot(x, y, color=color, linewidth=linewidth + 0.55, alpha=0.96, zorder=4)

        if not show_direction_arrows:
            return

        if direction == "single":
            self._draw_line_arrows(ax, line, color, reverse=False)
        elif direction == "double":
            self._draw_line_arrows(ax, line, color, reverse=False)
            self._draw_line_arrows(ax, line, color, reverse=True)

    def _route_direction(self, properties: dict[str, Any]) -> str | None:
        direction, _color = self._route_style(properties)
        return direction

    def _route_style(self, properties: dict[str, Any]) -> tuple[str | None, str | None]:
        return route_style(properties)

    def _draw_line_arrows(self, ax: Any, line: Any, color: str, *, reverse: bool) -> None:
        line_length = getattr(line, "length", 0)
        if line_length <= 0 or getattr(line, "is_empty", False):
            return

        fractions = (0.56,) if line_length > 0.02 else ()
        delta = min(line_length * 0.028, 0.0009)
        delta = max(delta, line_length * 0.010)

        for fraction in fractions:
            distance = line_length * fraction
            start = line.interpolate(max(distance - delta, 0))
            end = line.interpolate(min(distance + delta, line_length))
            if reverse:
                start, end = end, start
            if not all(math.isfinite(value) for value in (start.x, start.y, end.x, end.y)):
                continue

            self._draw_arrow(ax, start.x, start.y, end.x, end.y, "white", 1.35, 5, alpha=0.75)
            self._draw_arrow(ax, start.x, start.y, end.x, end.y, color, 0.75, 6, alpha=0.9)

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
        alpha: float = 1.0,
    ) -> None:
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops={
                "arrowstyle": "-|>",
                "color": color,
                "linewidth": linewidth,
                "mutation_scale": 7,
                "alpha": alpha,
                "shrinkA": 0,
                "shrinkB": 0,
            },
            annotation_clip=True,
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
        span_x *= 1.18
        span_y *= 1.18

        target_aspect = self._axes_box_aspect(ax)
        current_aspect = span_x / span_y if span_y else target_aspect
        if current_aspect < target_aspect:
            span_x = span_y * target_aspect
        elif current_aspect > target_aspect:
            span_y = span_x / target_aspect

        ax.set_xlim(center_x - span_x / 2, center_x + span_x / 2)
        ax.set_ylim(center_y - span_y / 2, center_y + span_y / 2)

    def _axes_box_aspect(self, ax: Any) -> float:
        fig = ax.figure
        box = ax.get_position()
        width = max(fig.get_figwidth() * box.width, 0.01)
        height = max(fig.get_figheight() * box.height, 0.01)
        return width / height

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

    def _attribute_rows(
        self,
        features: list[dict[str, Any]],
        attributes: list[str],
        max_features: int | None = 8,
    ) -> list[list[str]]:
        if not features or not attributes:
            return []
        visible_attributes = attributes[:8]
        rows = [visible_attributes]
        selected_features = features if max_features is None else features[:max_features]
        for feature in selected_features:
            props = feature.get("properties") or {}
            rows.append([str(props.get(attr, ""))[:34] for attr in visible_attributes])
        return rows

    def _chunk_attribute_rows(self, rows: list[list[str]], rows_per_page: int) -> list[list[list[str]]]:
        if not rows or not rows[0]:
            return []
        header, data_rows = rows[0], rows[1:]
        if not data_rows:
            return [[header]]
        return [
            [header, *data_rows[index:index + rows_per_page]]
            for index in range(0, len(data_rows), rows_per_page)
        ]

    def _table_rows_per_page(self, page_size: str, orientation: str) -> int:
        if page_size == "tabloid":
            return 34 if orientation == "portrait" else 24
        if page_size == "letter":
            return 26 if orientation == "portrait" else 18
        return 28 if orientation == "portrait" else 20

    def _draw_attribute_table(self, ax_table: Any, rows: list[list[str]], *, full_page: bool = False) -> None:
        if not rows or not rows[0]:
            return
        column_count = max(len(rows[0]), 1)
        table = ax_table.table(
            cellText=rows[1:],
            colLabels=rows[0],
            loc="upper center" if full_page else "center",
            cellLoc="left",
            colWidths=[1 / column_count] * column_count,
        )
        table.auto_set_font_size(False)
        if full_page:
            table.set_fontsize(6.0 if column_count <= 5 else 5.1)
            table.scale(1, 1.18 if column_count <= 5 else 1.08)
        else:
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
