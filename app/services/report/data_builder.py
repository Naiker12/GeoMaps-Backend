"""
GeoMaps — Constructor de Datos del Reporte.
Transforma datos crudos de los analyzers en el JSON universal del reporte.
"""
import logging
from typing import Any, Dict, List, Optional
from app.schemas.report_schemas import (
    UniversalReportJSON,
    KPIItem,
    ChartDefinition,
    TableRow,
)

logger = logging.getLogger(__name__)


class DataBuilder:
    """
    Construye el JSON universal del reporte a partir de datos espaciales crudos.
    Genera KPIs, charts y tablas automáticamente según el tipo de reporte.
    """

    def build(
        self,
        report_type: str,
        spatial_data: Dict[str, Any],
        ai_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UniversalReportJSON:
        """Construye el reporte universal a partir de los datos analizados."""
        metadata = metadata or {}

        # Título y subtítulo según tipo
        title, subtitle = self._get_title(report_type, spatial_data)
        zone_name = metadata.get("zone_name")
        zone_names = metadata.get("zone_names") or ([zone_name] if zone_name else [])
        if zone_name:
            title = f"Reporte Geoespacial - {zone_name}"
            subtitle = f"Analisis restringido a la zona {zone_name}"
        if report_type == "comparison_report" and zone_names:
            title = f"Reporte Comparativo - {' vs '.join(zone_names[:3])}"
            subtitle = f"Comparacion territorial entre {len(zone_names)} zonas"

        # KPIs según tipo
        kpis = self._build_kpis(report_type, spatial_data)

        # Charts según tipo
        charts = self._build_charts(report_type, spatial_data)

        # Tabla de indicadores
        indicator_table = self._build_indicator_table(report_type, spatial_data)

        report = UniversalReportJSON(
            type=report_type,
            title=title,
            subtitle=subtitle,
            user_id=metadata.get("user_id"),
            map_screenshot=metadata.get("map_screenshot"),
            map_screenshots=metadata.get("map_screenshots") or [],
            map_extent=metadata.get("bbox"),
            zones=zone_names,
            layers=metadata.get("layers") or [],
            kpis=kpis,
            charts=charts,
            indicator_table=indicator_table,
            ai_interpretation=ai_text,
            raw_spatial_data=spatial_data,
        )

        return report

    # ── Títulos ────────────────────────────────────

    def _get_title(self, report_type: str, data: Dict[str, Any]) -> tuple[str, str]:
        if report_type == "comparison_report":
            return "Reporte Comparativo Territorial", "Comparacion multi-zona del area seleccionada"
        titles = {
            "cadastral_report": (
                "Análisis Catastral Territorial",
                f"Zona de estudio — {data.get('layer_name', 'Área seleccionada')}"
            ),
            "hydrology_report": (
                "Análisis Hidrológico Espacial Inteligente",
                f"Evaluación de riesgo y cobertura — {data.get('hydro_layer', 'Área seleccionada')}"
            ),
            "general_report": (
                "Reporte Geoespacial General",
                "Análisis multi-capa del área seleccionada"
            ),
        }
        return titles.get(report_type, ("Reporte GeoMaps", "Análisis geoespacial"))

    # ── KPIs ──────────────────────────────────────

    def _build_kpis(self, report_type: str, data: Dict[str, Any]) -> List[KPIItem]:
        if report_type == "cadastral_report":
            return self._build_cadastral_kpis(data)
        elif report_type == "hydrology_report":
            return self._build_hydrology_kpis(data)
        else:
            return self._build_general_kpis(data)

    def _build_cadastral_kpis(self, data: Dict[str, Any]) -> List[KPIItem]:
        kpis = [
            KPIItem(
                label="Total Predios",
                value=data.get("total_predios", 0),
                color="blue",
                icon="building",
            ),
        ]

        dist = data.get("distribution_by_type", [])
        if dist:
            kpis.append(KPIItem(
                label="Categorías",
                value=len(dist),
                color="purple",
                icon="layers",
            ))
            kpis.append(KPIItem(
                label="Tipo Dominante",
                value=str(dist[0]["name"])[:25],
                color="green",
                icon="star",
            ))

        area_stats = data.get("area_stats", {})
        if area_stats.get("average"):
            kpis.append(KPIItem(
                label="Área Promedio",
                value=f"{area_stats['average']:,.0f}",
                unit="m²",
                color="amber",
                icon="ruler",
            ))

        value_stats = data.get("value_stats", {})
        if value_stats.get("average"):
            kpis.append(KPIItem(
                label="Valor Promedio",
                value=f"${value_stats['average']:,.0f}",
                color="teal",
                icon="dollar",
            ))

        return kpis[:5]

    def _build_hydrology_kpis(self, data: Dict[str, Any]) -> List[KPIItem]:
        risk = data.get("risk_estimation", {})
        kpis = [
            KPIItem(
                label="Riesgo de Inundación",
                value=risk.get("risk_level", "No determinado"),
                color="red" if risk.get("risk_index", 0) >= 0.55 else "amber",
                icon="alert-triangle",
            ),
            KPIItem(
                label="Índice de Riesgo",
                value=risk.get("risk_index", 0),
                color="red",
                icon="activity",
            ),
        ]

        hydro_count = data.get("hydro_count", 0)
        if hydro_count > 0:
            kpis.append(KPIItem(
                label="Cuerpos de Agua",
                value=hydro_count,
                color="blue",
                icon="droplets",
            ))

        layers = data.get("layers_summary", [])
        if layers:
            kpis.append(KPIItem(
                label="Capas Analizadas",
                value=len(layers),
                color="purple",
                icon="layers",
            ))

        return kpis[:5]

    def _build_general_kpis(self, data: Dict[str, Any]) -> List[KPIItem]:
        layers = data.get("layers_summary", [])
        total_features = sum(l.get("count", 0) for l in layers)
        zones = data.get("comparison_zones", [])

        kpis = [
            KPIItem(label="Capas Disponibles", value=len(layers), color="blue"),
            KPIItem(label="Total Elementos", value=total_features, color="green"),
        ]

        if zones:
            kpis.insert(0, KPIItem(label="Zonas Comparadas", value=len(zones), color="teal"))

        if layers:
            kpis.append(KPIItem(
                label="Capa Principal",
                value=str(layers[0]["name"])[:25],
                color="purple",
            ))

        return kpis

    # ── Charts ────────────────────────────────────

    def _build_charts(self, report_type: str, data: Dict[str, Any]) -> List[ChartDefinition]:
        charts = []

        if report_type == "cadastral_report":
            dist_type = data.get("distribution_by_type", [])
            if dist_type:
                chart_type = "pie" if len(dist_type) <= 7 else "bar"
                charts.append(ChartDefinition(
                    type=chart_type,
                    title="Distribución por Tipo de Predio",
                    data=dist_type,
                    x_key="name",
                    y_key="value",
                    color="#3B82F6",
                ))

            dist_zone = data.get("distribution_by_zone", [])
            if dist_zone:
                charts.append(ChartDefinition(
                    type="bar",
                    title="Distribución por Zona/Barrio",
                    data=dist_zone[:12],
                    x_key="name",
                    y_key="value",
                    color="#10B981",
                ))

        elif report_type == "hydrology_report":
            hydro_dist = data.get("hydro_distribution", [])
            if hydro_dist:
                charts.append(ChartDefinition(
                    type="bar",
                    title="Tipos de Cuerpos de Agua",
                    data=hydro_dist,
                    x_key="name",
                    y_key="value",
                    color="#3B82F6",
                ))

            land_cover = data.get("land_cover_stats", [])
            if land_cover:
                charts.append(ChartDefinition(
                    type="pie",
                    title="Distribución de Cobertura de Suelo",
                    data=land_cover,
                    x_key="name",
                    y_key="value",
                ))

        else:
            zones = data.get("comparison_zones", [])
            if zones:
                charts.append(ChartDefinition(
                    type="bar",
                    title="Elementos por Zona Comparada",
                    data=[
                        {"name": item.get("name", "Zona"), "value": item.get("feature_count", 0)}
                        for item in zones
                    ],
                    x_key="name",
                    y_key="value",
                    color="#1A56DB",
                ))

            layers = data.get("layers_summary", [])
            if layers:
                charts.append(ChartDefinition(
                    type="bar",
                    title="Elementos por Capa",
                    data=[{"name": l["name"][:20], "value": l["count"]} for l in layers[:10]],
                    x_key="name",
                    y_key="value",
                    color="#8B5CF6",
                ))

        return charts

    # ── Tabla de Indicadores ──────────────────────

    def _build_indicator_table(self, report_type: str, data: Dict[str, Any]) -> List[TableRow]:
        rows = []

        if report_type == "cadastral_report":
            rows.append(TableRow(label="Total de predios", value=data.get("total_predios", 0)))
            rows.append(TableRow(label="Muestra analizada", value=data.get("sample_size", 0)))

            area = data.get("area_stats", {})
            if area:
                rows.append(TableRow(label="Área promedio (m²)", value=area.get("average", 0)))
                rows.append(TableRow(label="Área mínima (m²)", value=area.get("minimum", 0)))
                rows.append(TableRow(label="Área máxima (m²)", value=area.get("maximum", 0)))

            val = data.get("value_stats", {})
            if val:
                rows.append(TableRow(label="Valor catastral promedio", value=f"${val.get('average', 0):,.0f}"))
                rows.append(TableRow(label="Valor catastral total", value=f"${val.get('sum', 0):,.0f}"))

        elif report_type == "hydrology_report":
            risk = data.get("risk_estimation", {})
            rows.append(TableRow(label="Índice de riesgo", value=risk.get("risk_index", 0)))
            rows.append(TableRow(label="Nivel de riesgo", value=risk.get("risk_level", "N/A")))
            rows.append(TableRow(label="Cuerpos de agua detectados", value=data.get("hydro_count", 0)))
            rows.append(TableRow(label="Metodología", value=risk.get("methodology", "Heurística")))

        else:
            zones = data.get("comparison_zones", [])
            for zone in zones[:8]:
                rows.append(TableRow(label=f"Zona: {zone.get('name')}", value=zone.get("feature_count", 0)))

            layers = data.get("layers_summary", [])
            for layer in layers[:8]:
                rows.append(TableRow(label=layer["name"], value=layer["count"]))

        return rows
