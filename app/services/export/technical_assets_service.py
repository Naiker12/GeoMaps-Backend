"""Technical chart/map asset generation for report PDFs.

This module produces print-oriented PNG assets from structured report data.
It deliberately keeps the PDF renderer independent from React dashboards.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class TechnicalAssetsService:
    """Generates report assets with Python plotting libraries."""

    def generate_assets(self, report_id: str, report_json: Dict[str, Any], output_dir: str) -> Dict[str, str]:
        asset_dir = Path(output_dir) / f"assets_{report_id}"
        asset_dir.mkdir(parents=True, exist_ok=True)

        assets: Dict[str, str] = {}
        chart_data = self._select_chart_data(report_json)

        try:
            assets["bar_chart"] = self._generate_bar_chart(chart_data, asset_dir / "bar_layers.png")
            assets["pie_chart"] = self._generate_pie_chart(chart_data, asset_dir / "pie_layers.png")
            assets["map_reference"] = self._generate_map_reference(report_json, asset_dir / "map_reference.png")
        except ImportError as exc:
            logger.warning("Matplotlib is not available; Typst report will render without generated charts: %s", exc)
        except Exception as exc:
            logger.warning("Could not generate one or more technical report assets: %s", exc, exc_info=True)

        return assets

    def _select_chart_data(self, report_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        charts = report_json.get("charts") or []
        for chart in charts:
            data = chart.get("data") or []
            if data:
                return data

        raw = report_json.get("raw_spatial_data") or {}
        layers = raw.get("layers_summary") or []
        if layers:
            return [{"name": item.get("name", "Capa"), "value": item.get("count", 0)} for item in layers]

        return [
            {"name": item.get("label", "Indicador"), "value": self._number_or_zero(item.get("value"))}
            for item in report_json.get("kpis", [])
        ]

    def _generate_bar_chart(self, data: List[Dict[str, Any]], output_path: Path) -> str:
        plt = self._get_pyplot()
        values = [self._number_or_zero(item.get("value")) for item in data[:12]]
        labels = [str(item.get("name") or item.get("label") or "Dato")[:28] for item in data[:12]]

        fig, ax = plt.subplots(figsize=(10, 5.5), dpi=220)
        bars = ax.barh(labels[::-1], values[::-1], color="#2563EB")
        ax.set_xlabel("Elementos")
        ax.set_title("Distribucion de elementos por capa", loc="left", fontsize=13, fontweight="bold")
        ax.grid(axis="x", linestyle="--", alpha=0.25)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.bar_label(bars, padding=4, fontsize=8)
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight")
        plt.close(fig)
        return str(output_path)

    def _generate_pie_chart(self, data: List[Dict[str, Any]], output_path: Path) -> str:
        plt = self._get_pyplot()
        cleaned = [
            (str(item.get("name") or item.get("label") or "Dato")[:24], self._number_or_zero(item.get("value")))
            for item in data[:8]
            if self._number_or_zero(item.get("value")) > 0
        ]
        if not cleaned:
            cleaned = [("Sin datos", 1)]

        labels, values = zip(*cleaned)
        fig, ax = plt.subplots(figsize=(7, 5.5), dpi=220)
        ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, textprops={"fontsize": 8})
        ax.set_title("Composicion porcentual", loc="left", fontsize=13, fontweight="bold")
        ax.axis("equal")
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight")
        plt.close(fig)
        return str(output_path)

    def _generate_map_reference(self, report_json: Dict[str, Any], output_path: Path) -> str:
        plt = self._get_pyplot()
        extent = report_json.get("map_extent") or {}
        xmin = float(extent.get("xmin", -75.6))
        ymin = float(extent.get("ymin", 10.3))
        xmax = float(extent.get("xmax", -75.45))
        ymax = float(extent.get("ymax", 10.48))

        fig, ax = plt.subplots(figsize=(10, 5.8), dpi=220)
        ax.set_facecolor("#EFF6FF")
        ax.fill([xmin, xmax, xmax, xmin], [ymin, ymin, ymax, ymax], color="#DBEAFE", alpha=0.85)
        ax.plot([xmin, xmax, xmax, xmin, xmin], [ymin, ymin, ymax, ymax, ymin], color="#DC2626", linewidth=2)
        ax.scatter([(xmin + xmax) / 2], [(ymin + ymax) / 2], color="#2563EB", s=35)
        ax.set_title("Mapa tecnico de referencia del area de estudio", loc="left", fontsize=13, fontweight="bold")
        ax.set_xlabel("Longitud")
        ax.set_ylabel("Latitud")
        ax.grid(True, linestyle="--", alpha=0.25)
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight")
        plt.close(fig)
        return str(output_path)

    def _get_pyplot(self):
        cache_dir = Path(tempfile.gettempdir()) / "geomaps_matplotlib_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt

    def _number_or_zero(self, value: Any) -> float:
        try:
            if isinstance(value, str):
                value = value.replace(".", "").replace(",", ".").replace("%", "")
            return float(value)
        except (TypeError, ValueError):
            return 0.0
