"""
GeoMaps — Motor de Reportes.
Orquestador principal que coordina el pipeline completo de generación de reportes.
"""
import logging
import time
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.ia.intent_classifier import IntentClassifier
from app.services.ia.zone_extractor import extract_zone_names
from app.services.ia.report_interpreter import ReportInterpreter
from app.services.spatial.cadastral_analyzer import CadastralAnalyzer
from app.services.spatial.hydrology_analyzer import HydrologyAnalyzer
from app.services.report.data_builder import DataBuilder
from app.schemas.report_schemas import UniversalReportJSON

logger = logging.getLogger(__name__)


class ReportEngine:
    """
    Orquestador principal del sistema de reportes.

    Flujo:
    - Clasificar intención del usuario
    - Seleccionar analizador espacial correspondiente
    - Ejecutar análisis en PostGIS
    - Generar interpretación con IA
    - Construir JSON estructurado
    - Devolver datos listos para el template React
    """

    ANALYZER_MAP = {
        "cadastral_report": CadastralAnalyzer,
        "hydrology_report": HydrologyAnalyzer,
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.classifier = IntentClassifier()
        self.interpreter = ReportInterpreter()
        self.data_builder = DataBuilder()

    async def generate(
        self,
        user_message: str,
        bbox: Optional[Dict[str, float]] = None,
        active_layers: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        zone_name: Optional[str] = None,
        zone_names: Optional[List[str]] = None,
        zone_geometry: Optional[Dict[str, Any]] = None,
        zone_geometries: Optional[List[Dict[str, Any]]] = None,
        specific_layers: Optional[List[str]] = None,
        map_screenshot: Optional[str] = None,
        map_screenshots: Optional[List[Dict[str, Any]]] = None,
        comparison_mode: bool = False,
    ) -> UniversalReportJSON:
        """
        Genera un reporte completo a partir de la consulta del usuario.
        """
        start_time = time.time()
        active_layers = active_layers or []
        specific_layers = specific_layers or []
        requested_zones = self._normalize_zone_list(zone_names or [])
        if zone_name:
            requested_zones = self._normalize_zone_list([*requested_zones, zone_name])
        extracted_zones = extract_zone_names(user_message)
        if extracted_zones:
            requested_zones = self._normalize_zone_list([*requested_zones, *extracted_zones])
        comparison_mode = comparison_mode or len(requested_zones) >= 2

        detected_zone = requested_zones[0] if requested_zones else self._extract_zone_name(user_message)
        zone_layer: Optional[str] = None
        resolved_zone_geometries = zone_geometries or []

        if comparison_mode and requested_zones:
            found_zones = await self._find_zones_in_db(requested_zones)
            resolved_zone_geometries = [
                {"name": item["name"], "geometry": item.get("geometry"), "bbox": item.get("bbox")}
                for item in found_zones
                if item.get("geometry")
            ] or resolved_zone_geometries
            bbox = self._combined_bbox([item.get("bbox") for item in found_zones]) or bbox
            zone_layer = next((str(item.get("layer_name")) for item in found_zones if item.get("layer_name")), None)

        if detected_zone and not zone_geometry and not comparison_mode:
            found_geometry, found_bbox, found_layer = await self._find_zone_in_db(detected_zone)
            zone_geometry = found_geometry
            bbox = found_bbox or bbox
            zone_layer = found_layer

        if detected_zone and zone_geometry and not bbox:
            bbox = self._bbox_from_geojson(zone_geometry)

        if detected_zone:
            active_layers = await self._resolve_zone_layers(
                zone_name=detected_zone,
                bbox=bbox,
                active_layers=active_layers,
                specific_layers=specific_layers,
                zone_layer=zone_layer,
            )
            logger.info(
                "Reporte restringido a zona '%s' con capas: %s",
                detected_zone,
                active_layers or ["sin capas resueltas"],
            )

        # Clasificar intención
        logger.info(f"Clasificando intención de reporte: '{user_message[:60]}...'")
        intent = await self.classifier.classify(user_message, active_layers, requested_zones)
        report_type = intent["type"]
        if comparison_mode:
            report_type = "comparison_report"
        logger.info(f"Intención clasificada: {report_type} (confianza: {intent['confidence']})")

        # Seleccionar y ejecutar analizador espacial
        AnalyzerClass = self.ANALYZER_MAP.get(report_type)

        if not AnalyzerClass:
            # Para tipos no soportados, intentar un análisis general con CadastralAnalyzer
            logger.warning(f"Tipo '{report_type}' sin analyzer dedicado, usando general")
            if report_type != "comparison_report":
                report_type = "general_report"
            # Usar HydrologyAnalyzer como general ya que tiene get_available_layers_in_bbox
            AnalyzerClass = HydrologyAnalyzer

        analyzer = AnalyzerClass(
            db=self.db,
            bbox=bbox,
            layers=active_layers
        )

        logger.info(f"Ejecutando análisis espacial con {AnalyzerClass.__name__}...")
        spatial_data = await analyzer.analyze()
        if comparison_mode and requested_zones:
            spatial_data["comparison_zones"] = await self._build_comparison_zone_summary(
                requested_zones,
                resolved_zone_geometries,
                active_layers,
            )

        # Generar interpretación con IA
        logger.info("Generando interpretación con IA...")
        ai_text = await self.interpreter.interpret(spatial_data, report_type)

        # Construir JSON universal del reporte
        logger.info("Construyendo JSON del reporte...")
        report = self.data_builder.build(
            report_type=report_type,
            spatial_data=spatial_data,
            ai_text=ai_text,
            metadata={
                "bbox": bbox,
                "user_id": user_id,
                "zone_name": detected_zone,
                "zone_names": requested_zones,
                "zone_geometry": zone_geometry,
                "zone_geometries": resolved_zone_geometries,
                "map_screenshot": map_screenshot,
                "map_screenshots": map_screenshots or [],
                "layers": active_layers,
            }
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Reporte generado en {elapsed_ms}ms — tipo: {report_type}, KPIs: {len(report.kpis)}, Charts: {len(report.charts)}")

        return report

    def _normalize_zone_list(self, values: List[str]) -> List[str]:
        zones: List[str] = []
        seen = set()
        for value in values:
            if not value:
                continue
            cleaned = re.sub(r"\s+", " ", str(value)).strip(" .,:;")
            key = self._normalize_text(cleaned)
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            zones.append(cleaned.title())
        return zones

    def _combined_bbox(self, bboxes: List[Optional[Dict[str, float]]]) -> Optional[Dict[str, float]]:
        valid = [bbox for bbox in bboxes if bbox]
        if not valid:
            return None
        return {
            "xmin": min(float(bbox["xmin"]) for bbox in valid),
            "ymin": min(float(bbox["ymin"]) for bbox in valid),
            "xmax": max(float(bbox["xmax"]) for bbox in valid),
            "ymax": max(float(bbox["ymax"]) for bbox in valid),
        }

    def _normalize_text(self, value: str) -> str:
        text_value = unicodedata.normalize("NFD", value or "")
        text_value = "".join(ch for ch in text_value if unicodedata.category(ch) != "Mn")
        return re.sub(r"\s+", " ", text_value).strip().lower()

    def _extract_zone_name(self, message: str) -> Optional[str]:
        normalized_message = self._normalize_text(message)
        patterns = [
            r"(?:zona|barrio|sector|area)\s+(?:de\s+|del\s+|la\s+|el\s+)?([a-z0-9\s]+?)(?=\s+(?:y\s+(?:barrio|zona|sector|area)|vs|versus|contra|con|para|en pdf|pdf|reporte|informe|analisis|genera|generar)|$)",
            r"(?:reporte|informe|analisis)\s+(?:de\s+|del\s+|para\s+)?(?:la\s+zona\s+|el\s+barrio\s+|sector\s+)?([a-z0-9\s]+?)(?=\s+(?:y\s+(?:barrio|zona|sector|area)|vs|versus|contra|con|para|en pdf|pdf)|$)",
        ]
        stop_words = {
            "actual", "visible", "esta zona", "esta area", "capas", "datos",
            "la zona visible actual", "la vista actual",
        }
        for pattern in patterns:
            match = re.search(pattern, normalized_message)
            if not match:
                continue
            candidate = match.group(1).strip(" .,:;")
            if candidate and candidate not in stop_words and len(candidate) > 2:
                return "Pie de la Popa" if candidate in {"pie de la papa", "pie de la poca"} else candidate.title()
        return None

    async def _find_zone_in_db(
        self,
        zone_name: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, float]], Optional[str]]:
        """Busca una zona por nombre en capas tipo barrio/sector/zona."""
        normalized = self._normalize_text(zone_name)
        variants = {normalized}
        if normalized in {"pie de la papa", "pie de la poca"}:
            variants.add("pie de la popa")

        query = text("""
            SELECT
                l.name AS layer_name,
                ST_AsGeoJSON(lf.geom) AS geojson,
                ST_XMin(lf.geom) AS xmin,
                ST_YMin(lf.geom) AS ymin,
                ST_XMax(lf.geom) AS xmax,
                ST_YMax(lf.geom) AS ymax
            FROM layers l
            JOIN layer_features lf ON l.id = lf.layer_id
            WHERE l.visibility != 'PRIVATE'
              AND (
                LOWER(l.name) LIKE ANY(:layer_patterns)
                OR LOWER(COALESCE(l.category, '')) LIKE ANY(:layer_patterns)
              )
              AND (
                LOWER(COALESCE(lf.display_name, '')) LIKE ANY(:zone_patterns)
                OR LOWER(lf.properties::text) LIKE ANY(:zone_patterns)
              )
            LIMIT 1
        """)

        zone_patterns = [f"%{item}%" for item in variants]
        layer_patterns = ["%barrio%", "%sector%", "%zona%", "%comuna%", "%localidad%"]

        try:
            result = await self.db.execute(
                query,
                {
                    "zone_patterns": zone_patterns,
                    "layer_patterns": layer_patterns,
                },
            )
            row = result.mappings().first()
            if not row:
                return None, None, None

            geometry = json.loads(row["geojson"])
            bbox = {
                "xmin": float(row["xmin"]),
                "ymin": float(row["ymin"]),
                "xmax": float(row["xmax"]),
                "ymax": float(row["ymax"]),
            }
            return geometry, bbox, str(row["layer_name"])
        except Exception as exc:
            logger.warning("No se pudo resolver zona '%s': %s", zone_name, exc)
            await self.db.rollback()
            return None, None, None

    async def _find_zones_in_db(self, zone_names: List[str]) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        for zone_name in zone_names:
            geometry, bbox, layer_name = await self._find_zone_in_db(zone_name)
            found.append({
                "name": zone_name,
                "geometry": geometry,
                "bbox": bbox,
                "layer_name": layer_name,
                "found": bool(geometry),
            })
        return found

    async def _build_comparison_zone_summary(
        self,
        zone_names: List[str],
        zone_geometries: List[Dict[str, Any]],
        active_layers: List[str],
    ) -> List[Dict[str, Any]]:
        summaries: List[Dict[str, Any]] = []
        geometry_by_name = {
            self._normalize_text(item.get("name", "")): item
            for item in zone_geometries
        }

        for zone_name in zone_names:
            zone_item = geometry_by_name.get(self._normalize_text(zone_name), {})
            bbox = zone_item.get("bbox") or self._bbox_from_geojson(zone_item.get("geometry") or {})
            feature_count = 0
            if bbox:
                try:
                    result = await self.db.execute(
                        text("""
                            SELECT COUNT(lf.id)
                            FROM layers l
                            JOIN layer_features lf ON l.id = lf.layer_id
                            WHERE l.visibility != 'PRIVATE'
                              AND (:has_layers = false OR l.name = ANY(:layers))
                              AND ST_Intersects(
                                lf.geom,
                                ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
                              )
                        """),
                        {
                            **bbox,
                            "layers": active_layers,
                            "has_layers": bool(active_layers),
                        },
                    )
                    feature_count = int(result.scalar() or 0)
                except Exception as exc:
                    logger.warning("No se pudo contar zona comparativa '%s': %s", zone_name, exc)
                    await self.db.rollback()

            summaries.append({
                "name": zone_name,
                "found": bool(zone_item),
                "feature_count": feature_count,
                "bbox": bbox,
            })
        return summaries

    def _bbox_from_geojson(self, geometry: Dict[str, Any]) -> Optional[Dict[str, float]]:
        coords: List[float] = []

        def collect(value: Any) -> None:
            if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(n, (int, float)) for n in value[:2]):
                coords.extend([float(value[0]), float(value[1])])
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    collect(item)

        collect(geometry.get("coordinates"))
        xs = coords[0::2]
        ys = coords[1::2]
        if not xs or not ys:
            return None
        return {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}

    async def _resolve_zone_layers(
        self,
        zone_name: str,
        bbox: Optional[Dict[str, float]],
        active_layers: List[str],
        specific_layers: List[str],
        zone_layer: Optional[str],
    ) -> List[str]:
        if specific_layers:
            normalized_specific = [self._normalize_text(layer) for layer in specific_layers]
            return [
                layer for layer in active_layers
                if any(item in self._normalize_text(layer) or self._normalize_text(layer) in item for item in normalized_specific)
            ] or specific_layers

        if active_layers:
            zone_like = [
                layer for layer in active_layers
                if any(word in self._normalize_text(layer) for word in ["barrio", "sector", "zona", "comuna", "localidad"])
            ]
            if zone_like:
                return zone_like[:1]

        if zone_layer:
            return [zone_layer]

        if not bbox:
            return active_layers[:1]

        try:
            result = await self.db.execute(
                text("""
                    SELECT l.name, COUNT(lf.id) AS feature_count
                    FROM layers l
                    JOIN layer_features lf ON l.id = lf.layer_id
                    WHERE l.visibility != 'PRIVATE'
                      AND ST_Intersects(
                        lf.geom,
                        ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
                      )
                    GROUP BY l.name
                    ORDER BY
                      CASE
                        WHEN LOWER(l.name) LIKE '%barrio%' THEN 0
                        WHEN LOWER(l.name) LIKE '%sector%' THEN 1
                        ELSE 2
                      END,
                      feature_count DESC
                    LIMIT 1
                """),
                bbox,
            )
            row = result.fetchone()
            return [str(row[0])] if row else active_layers[:1]
        except Exception as exc:
            logger.warning("No se pudieron resolver capas para zona '%s': %s", zone_name, exc)
            await self.db.rollback()
            return active_layers[:1]

    async def get_supported_types(self) -> List[Dict[str, str]]:
        """Lista los tipos de reporte soportados."""
        return [
            {
                "type": "cadastral_report",
                "name": "Análisis Catastral",
                "description": "Análisis de predios, propiedades y distribución territorial",
                "icon": "building",
            },
            {
                "type": "hydrology_report",
                "name": "Análisis Hidrológico",
                "description": "Evaluación de riesgo de inundación y cuencas hidrográficas",
                "icon": "droplets",
            },
            {
                "type": "general_report",
                "name": "Reporte General",
                "description": "Análisis multi-capa del área seleccionada",
                "icon": "map-pin",
            },
        ]
