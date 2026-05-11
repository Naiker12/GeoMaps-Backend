"""Typst renderer for professional GIS report PDFs."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.services.export.technical_assets_service import TechnicalAssetsService

logger = logging.getLogger(__name__)


class TypstPDFService:
    """Renders structured report JSON into a professional Typst PDF."""

    def __init__(self, pdf_output_dir: str | None = None, timeout_seconds: int = 60):
        self.pdf_output_dir = pdf_output_dir or tempfile.mkdtemp(prefix="geomaps_typst_pdfs_")
        self.timeout_seconds = timeout_seconds
        self.assets = TechnicalAssetsService()
        Path(self.pdf_output_dir).mkdir(parents=True, exist_ok=True)

    async def generate_pdf(self, report_id: str, report_json: Dict[str, Any]) -> str:
        if sys.platform == "win32":
            return await asyncio.to_thread(self._generate_pdf_sync, report_id, report_json)
        return self._generate_pdf_sync(report_id, report_json)

    def _generate_pdf_sync(self, report_id: str, report_json: Dict[str, Any]) -> str:
        assets = self.assets.generate_assets(report_id, report_json, self.pdf_output_dir)
        typ_path = Path(self.pdf_output_dir) / f"report_{report_id}.typ"
        pdf_path = Path(self.pdf_output_dir) / f"report_{report_id}.pdf"
        typ_path.write_text(self._build_typst_source(report_json, assets), encoding="utf-8")

        self._compile_typst(typ_path, pdf_path)

        return str(pdf_path)

    def _compile_typst(self, typ_path: Path, pdf_path: Path) -> None:
        typst_cli = shutil.which("typst")
        if typst_cli:
            result = subprocess.run(
                [typst_cli, "compile", str(typ_path), str(pdf_path)],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                logger.error("Typst render failed: %s", result.stderr or result.stdout)
                raise RuntimeError(f"Typst no pudo generar el PDF: {result.stderr or result.stdout}")
            return

        try:
            import typst
        except ImportError as exc:
            raise RuntimeError("Typst no disponible. Instala el paquete 'typst' o el Typst CLI.") from exc

        try:
            typst.compile(str(typ_path), output=str(pdf_path), root=str(typ_path.parent))
        except Exception as exc:
            logger.error("Typst Python render failed: %s", exc)
            raise RuntimeError(f"Typst no pudo generar el PDF: {exc}") from exc

    def _build_typst_source(self, report: Dict[str, Any], assets: Dict[str, str]) -> str:
        title = self._t(report.get("title") or "Reporte Geoespacial")
        subtitle = self._t(report.get("subtitle") or "Documento tecnico GIS automatizado")
        location = self._t(report.get("location") or "Cartagena, Bolivar")
        report_type = self._t(report.get("type") or "general_report")
        generated_at = self._format_date(report.get("generated_at"))
        ai_interpretation = self._t(report.get("ai_interpretation") or "No se genero interpretacion IA para este reporte.")
        kpis = report.get("kpis") or []
        tables = report.get("indicator_table") or []
        raw = report.get("raw_spatial_data") or {}
        risk = raw.get("risk_estimation") or {}
        assets_typ = {key: self._typst_path(value) for key, value in assets.items()}

        return f"""
#set document(title: "{title}", author: "GeoMaps AI Analytics Engine")
#set text(font: "Liberation Sans", size: 10pt, fill: rgb("#1E293B"))
#set page(
  paper: "a4",
  margin: (top: 24mm, bottom: 22mm, left: 20mm, right: 20mm),
  header: context {{
    if counter(page).get().first() > 1 {{
      grid(
        columns: (1fr, auto),
        align: (left + horizon, right + horizon),
        text(size: 8pt, weight: "bold", fill: rgb("#1E3A5F"))[GEOMAPS],
        text(size: 7pt, fill: rgb("#64748B"))[{title}]
      )
      line(length: 100%, stroke: 0.5pt + rgb("#CBD5E1"))
    }}
  }},
  footer: context {{
    line(length: 100%, stroke: 0.5pt + rgb("#CBD5E1"))
    grid(
      columns: (1fr, auto),
      align: (left + horizon, right + horizon),
      text(size: 7pt, fill: rgb("#64748B"))[GeoMaps AI Analytics Engine | {generated_at}],
      text(size: 7pt, fill: rgb("#64748B"))[Pag. #counter(page).display("1") de #counter(page).final().first()]
    )
  }},
)
#set par(justify: true, leading: 0.65em)
#show heading.where(level: 1): it => {{
  v(14pt)
  block(width: 100%, fill: rgb("#1E3A5F"), inset: (x: 10pt, y: 6pt), radius: 2pt)[
    #text(fill: white, size: 12pt, weight: "bold")[#it.body]
  ]
  v(8pt)
}}
#show heading.where(level: 2): it => {{
  v(8pt)
  text(fill: rgb("#2563EB"), size: 11pt, weight: "bold")[#it.body]
  v(3pt)
  line(length: 100%, stroke: 0.5pt + rgb("#BFDBFE"))
  v(6pt)
}}

#page(header: none, footer: none, margin: 0mm)[
  #block(width: 100%, height: 100%, fill: rgb("#0F172A"))[
    #block(width: 100%, height: 9mm, fill: rgb("#2563EB"))
    #v(24mm)
    #align(center)[
      #text(fill: rgb("#60A5FA"), size: 24pt, weight: "bold", tracking: 3pt)[GEOMAPS]
      #v(5mm)
      #text(fill: white, size: 27pt, weight: "bold")[{title}]
      #v(4mm)
      #text(fill: rgb("#CBD5E1"), size: 13pt)[{subtitle}]
      #v(14mm)
      #grid(columns: (1fr, 1fr, 1fr), column-gutter: 8pt,
        {self._kpi_cover_cells(kpis)}
      )
      #v(18mm)
      #text(fill: rgb("#94A3B8"), size: 9pt)[Tipo: {report_type} | Area: {location} | Fecha: {generated_at}]
    ]
    #place(bottom)[
      #block(width: 100%, height: 13mm, fill: rgb("#2563EB"))[
        #align(center + horizon)[#text(fill: white, size: 8pt)[PDF vectorial generado con Typst | Spatial Engine + AI Interpretation]]
      ]
    ]
  ]
]

= Resumen Ejecutivo

#grid(columns: (1fr, 1fr, 1fr, 1fr), column-gutter: 7pt,
  {self._kpi_summary_cells(kpis)}
)

#v(8pt)
Este documento tecnico consolida resultados GIS reales, estadisticas espaciales e interpretacion automatizada de IA. El objetivo es entregar un informe estable para revision de ingenieria, planeacion territorial y toma de decisiones institucionales.

= Area de Estudio y Mapa Tecnico

== Localizacion

#table(
  columns: (1fr, 2fr),
  fill: (col, row) => if calc.odd(row) {{ rgb("#F8FAFC") }} else {{ white }},
  stroke: 0.5pt + rgb("#E2E8F0"),
  inset: (x: 8pt, y: 6pt),
  [Campo], [Valor],
  [Ubicacion], [{location}],
  [Sistema de referencia], [WGS84 / EPSG:4326],
  [Tipo de reporte], [{report_type}],
  [Fecha de generacion], [{generated_at}],
)

{self._image_block(assets_typ.get("map_reference"), "Figura 1. Mapa tecnico de referencia del area de estudio.")}

= Analisis Espacial

== Distribucion de Elementos

{self._image_block(assets_typ.get("bar_chart"), "Figura 2. Distribucion tecnica de elementos por capa.")}

== Composicion Porcentual

{self._image_block(assets_typ.get("pie_chart"), "Figura 3. Composicion porcentual de capas o indicadores.")}

== Tabla de Indicadores

{self._indicator_table(tables)}

= Analisis Hidrologico e Indicadores de Riesgo

{self._risk_block(risk)}

= Interpretacion Inteligente

#block(
  fill: rgb("#EFF6FF"),
  stroke: (left: 4pt + rgb("#2563EB"), rest: 0.5pt + rgb("#BFDBFE")),
  inset: (x: 14pt, y: 12pt),
  radius: 4pt,
)[
  #text(fill: rgb("#1D4ED8"), size: 9pt, weight: "bold")[INTERPRETACION GENERADA POR IA]
  #v(6pt)
  {ai_interpretation}
]

= Metadatos y Trazabilidad

#table(
  columns: (1fr, 2fr),
  fill: (col, row) => if calc.odd(row) {{ rgb("#F8FAFC") }} else {{ white }},
  stroke: 0.5pt + rgb("#E2E8F0"),
  inset: (x: 8pt, y: 6pt),
  [Campo], [Valor],
  [Motor de analisis], [GeoMaps Spatial Engine],
  [Motor de interpretacion], [GeoMaps AI / Gemini],
  [Motor de exportacion], [Typst PDF vectorial],
  [Clasificacion], [Documento tecnico],
)
"""

    def _kpi_cover_cells(self, kpis: List[Dict[str, Any]]) -> str:
        selected = (kpis[:3] or [{"label": "Indicadores", "value": "N/D"}])
        return ",\n".join(
            f'block(fill: rgb("#1E293B"), inset: 10pt, radius: 4pt)[#text(fill: rgb("#94A3B8"), size: 7pt)[{self._t(item.get("label"))}] #linebreak() #text(fill: rgb("#60A5FA"), size: 14pt, weight: "bold")[{self._t(item.get("value"))}]]'
            for item in selected
        )

    def _kpi_summary_cells(self, kpis: List[Dict[str, Any]]) -> str:
        selected = (kpis[:4] or [{"label": "Indicadores", "value": "N/D", "unit": ""}])
        return ",\n".join(
            f'block(fill: rgb("#F8FAFC"), stroke: 0.5pt + rgb("#CBD5E1"), inset: 9pt, radius: 4pt)[#text(size: 7pt, fill: rgb("#64748B"))[{self._t(item.get("label"))}] #linebreak() #text(size: 13pt, weight: "bold", fill: rgb("#2563EB"))[{self._t(item.get("value"))} {self._t(item.get("unit") or "")}]]'
            for item in selected
        )

    def _indicator_table(self, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return '#block(fill: rgb("#F8FAFC"), inset: 10pt)[No hay indicadores tabulares disponibles.]'

        cells = []
        for row in rows[:18]:
            cells.append(f'[{self._t(row.get("label"))}], [{self._t(row.get("value"))}],')
        return f"""
#table(
  columns: (2fr, 1fr),
  fill: (col, row) => if row == 0 {{ rgb("#1E3A5F") }} else if calc.odd(row) {{ rgb("#F8FAFC") }} else {{ white }},
  stroke: 0.5pt + rgb("#E2E8F0"),
  inset: (x: 8pt, y: 6pt),
  table.header(text(fill: white, weight: "bold")[Indicador], text(fill: white, weight: "bold")[Valor]),
  {"".join(cells)}
)
"""

    def _risk_block(self, risk: Dict[str, Any]) -> str:
        risk_index = self._t(risk.get("risk_index", "N/D"))
        risk_level = self._t(risk.get("risk_level", "No determinado"))
        methodology = self._t(risk.get("methodology", "No especificada"))
        return f"""
#grid(columns: (1fr, 1fr), column-gutter: 10pt,
  block(fill: rgb("#FEF3C7"), stroke: 0.5pt + rgb("#F59E0B"), inset: 10pt, radius: 4pt)[
    #text(size: 8pt, fill: rgb("#92400E"))[Nivel de riesgo] #linebreak()
    #text(size: 16pt, weight: "bold", fill: rgb("#B45309"))[{risk_level}]
  ],
  block(fill: rgb("#EFF6FF"), stroke: 0.5pt + rgb("#93C5FD"), inset: 10pt, radius: 4pt)[
    #text(size: 8pt, fill: rgb("#1D4ED8"))[Indice de riesgo] #linebreak()
    #text(size: 16pt, weight: "bold", fill: rgb("#2563EB"))[{risk_index}]
  ],
)
#v(8pt)
#block(fill: rgb("#F8FAFC"), stroke: 0.5pt + rgb("#CBD5E1"), inset: 10pt, radius: 4pt)[
  #text(weight: "bold")[Metodologia:] {methodology}
]
"""

    def _image_block(self, path: str | None, caption: str) -> str:
        if not path:
            return '#block(fill: rgb("#F8FAFC"), inset: 10pt)[Asset cartografico no disponible en esta generacion.]'
        return f"""
#block(stroke: 0.5pt + rgb("#CBD5E1"), inset: 4pt, radius: 4pt)[
  #image("{path}", width: 100%)
]
#align(center)[#text(size: 8pt, fill: rgb("#64748B"), style: "italic")[{self._t(caption)}]]
"""

    def _format_date(self, value: Any) -> str:
        if not value:
            return datetime.now().strftime("%Y-%m-%d")
        return self._t(str(value).split("T")[0])

    def _typst_path(self, value: str) -> str:
        path = Path(value).resolve()
        try:
            return path.relative_to(Path(self.pdf_output_dir).resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def _t(self, value: Any) -> str:
        text = "" if value is None else str(value)
        replacements = {
            "\\": "\\\\",
            "[": "\\[",
            "]": "\\]",
            "#": "\\#",
            "*": "\\*",
            "_": "\\_",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text
