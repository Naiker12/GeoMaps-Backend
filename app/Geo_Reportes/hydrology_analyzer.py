"""
GeoMaps — Analizador Hidrológico.
Analiza riesgo de inundación, cuencas y cobertura de suelo usando PostGIS.
Nota: No usa Rasterio/DEM por ahora. Usa aproximaciones con datos vectoriales.
"""
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.Geo_Reportes.base_spatial import BaseSpatialAnalyzer

logger = logging.getLogger(__name__)


class HydrologyAnalyzer(BaseSpatialAnalyzer):
    """
    Ejecuta análisis hidrológico sobre el área visible del mapa.
    Usa PostGIS para consultas espaciales de cuencas, ríos y riesgo.
    """

    HYDRO_LAYER_KEYWORDS = ["rio", "cuenca", "hidro", "agua", "drenaje", "cauce", "inundacion", "flood"]
    LAND_COVER_KEYWORDS = ["cobertura", "uso_suelo", "land_cover", "vegetacion", "suelo"]

    async def analyze(self) -> Dict[str, Any]:
        """Ejecuta el análisis hidrológico y retorna datos estructurados."""
        results: Dict[str, Any] = {}

        # Identificar capas hídricas disponibles
        hydro_layer = await self._find_layer_by_keywords(self.HYDRO_LAYER_KEYWORDS)
        land_cover_layer = await self._find_layer_by_keywords(self.LAND_COVER_KEYWORDS)

        # Resumen de capas disponibles en la zona
        layers_in_bbox = await self.get_available_layers_in_bbox()
        results["layers_summary"] = layers_in_bbox

        # Análisis de capa hidrológica si existe
        if hydro_layer:
            results["hydro_layer"] = hydro_layer
            results["hydro_count"] = await self.count_features_in_bbox(hydro_layer)
            hydro_features = await self.query_features_in_bbox(hydro_layer, limit=200)

            if hydro_features:
                sample = hydro_features[0]
                fields = list(sample.keys())

                # Distribución por tipo de cuerpo de agua
                type_field = self._find_field(fields, ["tipo", "type", "clase", "nombre", "categoria"])
                if type_field:
                    results["hydro_distribution"] = await self.get_field_distribution(
                        hydro_layer, type_field, limit=10
                    )

        # Análisis de cobertura de suelo si existe
        if land_cover_layer:
            results["land_cover_layer"] = land_cover_layer
            land_features = await self.query_features_in_bbox(land_cover_layer, limit=300)
            if land_features:
                fields = list(land_features[0].keys())
                cover_field = self._find_field(fields, ["tipo", "cobertura", "uso", "type", "clase", "categoria"])
                if cover_field:
                    results["land_cover_stats"] = await self.get_field_distribution(
                        land_cover_layer, cover_field, limit=8
                    )

        # Análisis multi-capa en la zona (resumen general)
        results["zone_analysis"] = await self._analyze_zone_composition()

        # Estimación de riesgo (aproximación basada en datos disponibles)
        results["risk_estimation"] = self._estimate_flood_risk(results)

        return results

    async def _find_layer_by_keywords(self, keywords: List[str]) -> Optional[str]:
        """Busca una capa que coincida con los keywords."""
        try:
            # Primero en capas activas
            if self.layers:
                for layer in self.layers:
                    for kw in keywords:
                        if kw in layer.lower():
                            return layer

            # Luego en BD
            query = text("SELECT name FROM layers WHERE visibility != 'PRIVATE' ORDER BY name")
            result = await self.db.execute(query)
            all_layers = [str(row[0]) for row in result.fetchall()]

            for name in all_layers:
                for kw in keywords:
                    if kw in name.lower():
                        return name

            return None
        except Exception as e:
            logger.error(f"Error buscando capa hidrológica: {e}")
            return None

    def _find_field(self, available: List[str], candidates: List[str]) -> Optional[str]:
        """Busca campo por coincidencia parcial."""
        available_lower = {f.lower(): f for f in available}
        for candidate in candidates:
            if candidate.lower() in available_lower:
                return available_lower[candidate.lower()]
            for key, original in available_lower.items():
                if candidate.lower() in key:
                    return original
        return None

    async def _analyze_zone_composition(self) -> List[Dict[str, Any]]:
        """Analiza la composición general de la zona por capa."""
        try:
            layers_in_bbox = await self.get_available_layers_in_bbox()
            return [
                {
                    "name": layer["name"],
                    "feature_count": layer["count"],
                }
                for layer in layers_in_bbox[:10]
            ]
        except Exception as e:
            logger.error(f"Error en análisis de composición: {e}")
            return []

    def _estimate_flood_risk(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Estimación aproximada de riesgo de inundación.
        Sin DEM, usamos heurísticas basadas en datos disponibles.
        """
        risk_score = 0.3  # Base: riesgo bajo por defecto

        # Si hay cuerpos de agua cercanos, aumentar riesgo
        hydro_count = analysis_data.get("hydro_count", 0)
        if hydro_count > 0:
            risk_score += min(hydro_count / 50, 0.3)  # Más cuerpos de agua = más riesgo

        # Si hay cobertura urbana dominante, mayor escorrentía
        land_cover = analysis_data.get("land_cover_stats", [])
        for cover in land_cover:
            name_lower = str(cover.get("name", "")).lower()
            if any(kw in name_lower for kw in ["urban", "construi", "impermeab"]):
                risk_score += 0.2
                break

        risk_score = min(risk_score, 1.0)

        if risk_score >= 0.75:
            level = "Muy Alto"
        elif risk_score >= 0.55:
            level = "Alto"
        elif risk_score >= 0.35:
            level = "Medio"
        else:
            level = "Bajo"

        return {
            "risk_index": round(risk_score, 2),
            "risk_level": level,
            "methodology": "Estimación heurística basada en proximidad a cuerpos de agua y cobertura de suelo",
        }