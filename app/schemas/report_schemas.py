"""
GeoMaps — Schemas del Sistema de Reportes IA
Contrato universal entre el backend (Python) y el frontend (React templates).
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID, uuid4


# ── KPIs / Tarjetas Resumen ──────────────────────────
class KPIItem(BaseModel):
    label: str
    value: str | int | float
    unit: Optional[str] = None
    color: str = "blue"  # red | blue | green | amber | teal | purple
    icon: Optional[str] = None


# ── Definición de Gráfica ────────────────────────────
class ChartDefinition(BaseModel):
    type: str = "bar"  # bar | line | pie | area | scatter
    title: str
    data: List[Dict[str, Any]]
    x_key: str = "name"
    y_key: str = "value"
    color: Optional[str] = "#3B82F6"


# ── Fila de Tabla ────────────────────────────────────
class TableRow(BaseModel):
    label: str
    value: str | int | float


# ── Leyenda del Mapa ─────────────────────────────────
class MapLegendItem(BaseModel):
    title: str
    visible: bool = True
    items: List[Dict[str, str]] = Field(default_factory=list)


class MapScreenshot(BaseModel):
    label: str
    data: str


# ── JSON Universal del Reporte ───────────────────────
class UniversalReportJSON(BaseModel):
    """
    Schema principal. Es el contrato entre el backend y los templates React.
    El mismo JSON sirve para cualquier tipo de reporte y cualquier formato
    de exportación (PDF, HTML, DOCX en el futuro).
    """
    # Metadatos
    id: UUID = Field(default_factory=uuid4)
    type: str  # hydrology_report | cadastral_report | flood_report | terrain_report | environmental_report
    title: str
    subtitle: Optional[str] = None
    location: str = "Cartagena, Bolívar"
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    user_id: Optional[str] = None

    # Mapa
    map_screenshot: Optional[str] = None
    map_screenshots: List[MapScreenshot] = Field(default_factory=list)
    map_legend: List[MapLegendItem] = Field(default_factory=list)
    map_extent: Optional[Dict[str, float]] = None  # {xmin, ymin, xmax, ymax}
    zones: List[str] = Field(default_factory=list)
    layers: List[str] = Field(default_factory=list)

    # KPIs
    kpis: List[KPIItem] = Field(default_factory=list)

    # Gráficas
    charts: List[ChartDefinition] = Field(default_factory=list)

    # Tabla de indicadores
    indicator_table: List[TableRow] = Field(default_factory=list)

    # Análisis IA
    ai_interpretation: str = ""
    ai_model_used: Optional[str] = None

    # Datos crudos (para exportación CSV/DOCX futura)
    raw_spatial_data: Dict[str, Any] = Field(default_factory=dict)


# ── Request del Frontend ─────────────────────────────
class ReportRequest(BaseModel):
    message: str
    bbox: Optional[Dict[str, float]] = None  # {xmin, ymin, xmax, ymax}
    active_layers: List[str] = Field(default_factory=list)
    map_screenshot: Optional[str] = None
    map_screenshots: List[MapScreenshot] = Field(default_factory=list)
    conversation_id: Optional[UUID] = None
    zone_name: Optional[str] = None
    zone_names: List[str] = Field(default_factory=list)
    zone_geometry: Optional[Dict[str, Any]] = None
    zone_geometries: List[Dict[str, Any]] = Field(default_factory=list)
    comparison_mode: bool = False
    specific_layers: List[str] = Field(default_factory=list)


# ── Response de Status ───────────────────────────────
class ReportStatusResponse(BaseModel):
    report_id: str | UUID
    status: str  # processing | completed | failed
    progress: int = 0
    report_data: Optional[Dict[str, Any]] = None
    download_url: Optional[str] = None
    error_message: Optional[str] = None
    renderer: Optional[str] = None  # typst
    zones: List[str] = Field(default_factory=list)
    layers: List[str] = Field(default_factory=list)
    kpis: List[Dict[str, Any]] = Field(default_factory=list)
    progress_message: Optional[str] = None


# ── Response de Generación ───────────────────────────
class ReportGenerateResponse(BaseModel):
    report_id: str | UUID
    status: str = "processing"
