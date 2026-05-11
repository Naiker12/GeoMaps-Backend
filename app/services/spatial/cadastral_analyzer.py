"""
GeoMaps — Analizador Catastral.
Analiza predios, lotes y propiedades dentro de un área geográfica.
"""
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.spatial.base_spatial import BaseSpatialAnalyzer

logger = logging.getLogger(__name__)


class CadastralAnalyzer(BaseSpatialAnalyzer):
    """
    Ejecuta análisis catastral sobre los datos disponibles en la zona visible del mapa.
    Consulta predios, distribución por tipo, valores catastrales y áreas.
    """

    # Capas conocidas que contienen datos catastrales
    CADASTRAL_LAYER_KEYWORDS = ["predio", "lote", "catast", "parcel", "propiedad"]

    async def analyze(self) -> Dict[str, Any]:
        """Ejecuta el análisis catastral completo y retorna datos estructurados."""
        results: Dict[str, Any] = {}

        # Detectar capas catastrales disponibles
        cadastral_layer = await self._find_cadastral_layer()
        if not cadastral_layer:
            logger.warning("No se encontró capa catastral en la BD")
            results["error"] = "No se encontraron capas catastrales en el área"
            return results

        results["layer_name"] = cadastral_layer

        # Conteo total de predios en la zona
        total = await self.count_features_in_bbox(cadastral_layer)
        results["total_predios"] = total

        # Obtener features para análisis detallado
        features = await self.query_features_in_bbox(cadastral_layer, limit=500)
        results["sample_size"] = len(features)

        # Detectar campos disponibles y analizar
        if features:
            sample = features[0]
            available_fields = list(sample.keys())
            results["available_fields"] = available_fields

            # Distribución por tipo de predio
            type_field = self._find_field(available_fields, ["tipo", "type", "clase", "uso", "destino", "categoria"])
            if type_field:
                results["distribution_by_type"] = await self.get_field_distribution(
                    cadastral_layer, type_field, limit=10
                )

            # Distribución por barrio/sector
            zone_field = self._find_field(available_fields, ["barrio", "sector", "zona", "localidad", "comuna", "neighborhood"])
            if zone_field:
                results["distribution_by_zone"] = await self.get_field_distribution(
                    cadastral_layer, zone_field, limit=15
                )

            # Estadísticas numéricas (área, valor, etc.)
            area_field = self._find_field(available_fields, ["area", "superficie", "area_m2", "area_terreno", "area_construida"])
            if area_field:
                results["area_stats"] = await self.get_numeric_stats(cadastral_layer, area_field)

            value_field = self._find_field(available_fields, ["valor", "avaluo", "valor_catastral", "price", "value"])
            if value_field:
                results["value_stats"] = await self.get_numeric_stats(cadastral_layer, value_field)

            # Top predios más valiosos o más grandes
            results["top_features"] = self._extract_top_features(features, value_field or area_field, limit=10)

        return results

    async def _find_cadastral_layer(self) -> Optional[str]:
        """Busca la primera capa que parece ser catastral."""
        try:
            # Si el usuario tiene capas activas, buscar ahí primero
            if self.layers:
                for layer in self.layers:
                    for keyword in self.CADASTRAL_LAYER_KEYWORDS:
                        if keyword in layer.lower():
                            return layer

            # Si no, buscar en la BD
            query = text("""
                SELECT name FROM layers
                WHERE visibility != 'PRIVATE'
                ORDER BY name
            """)
            result = await self.db.execute(query)
            all_layers = [str(row[0]) for row in result.fetchall()]

            for layer_name in all_layers:
                for keyword in self.CADASTRAL_LAYER_KEYWORDS:
                    if keyword in layer_name.lower():
                        return layer_name

            # Fallback: usar la primera capa activa
            if self.layers:
                return self.layers[0]

            return None
        except Exception as e:
            logger.error(f"Error buscando capa catastral: {e}")
            return None

    def _find_field(self, available: List[str], candidates: List[str]) -> Optional[str]:
        """Busca el primer campo que coincida con los candidatos (case-insensitive)."""
        available_lower = {f.lower(): f for f in available}
        for candidate in candidates:
            if candidate.lower() in available_lower:
                return available_lower[candidate.lower()]
            # Búsqueda parcial
            for key, original in available_lower.items():
                if candidate.lower() in key:
                    return original
        return None

    def _extract_top_features(
        self,
        features: List[Dict[str, Any]],
        sort_field: Optional[str],
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Extrae los top features según un campo numérico."""
        if not sort_field or not features:
            return features[:limit]

        try:
            sorted_features = sorted(
                features,
                key=lambda f: float(f.get(sort_field, 0) or 0),
                reverse=True
            )
            return sorted_features[:limit]
        except (ValueError, TypeError):
            return features[:limit]
