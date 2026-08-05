"""
GeoMaps — Clasificador de Intención para Reportes.
Determina qué tipo de reporte solicita el usuario usando el LLM.
"""
import logging
import json
from typing import Any, Dict, List, Optional
from app.shared.core.config import settings
from app.infrastructure.ia_llm_client import LLMProviderFactory
from app.schemas.ia import Message

logger = logging.getLogger(__name__)

# Tipos de reporte soportados
REPORT_TYPES = {
    "comparison_report": {
        "keywords": ["compara", "comparar", "comparacion", "comparación", "versus", "vs", "diferencia", "contrastar"],
        "description": "Comparacion territorial entre dos o mas barrios, zonas o sectores"
    },
    "cadastral_report": {
        "keywords": ["catastral", "predio", "lote", "propiedad", "parcela", "terreno", "avalúo", "inmueble"],
        "description": "Análisis de predios, propiedades y distribución catastral"
    },
    "hydrology_report": {
        "keywords": ["hidrológico", "inundación", "cuenca", "río", "agua", "drenaje", "precipitación", "flood"],
        "description": "Análisis hidrológico, riesgo de inundación y cuencas"
    },
    "general_report": {
        "keywords": ["reporte", "informe", "análisis", "resumen", "estadísticas"],
        "description": "Reporte general multi-capa del área"
    },
}


class IntentClassifier:
    """
    Clasifica la intención del usuario para determinar el tipo de reporte.
    Usa primero una heurística de keywords y, si no es concluyente, el LLM.
    """

    def classify_by_keywords(self, message: str, active_layers: List[str], zone_names: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """Clasificación rápida por keywords sin llamar al LLM."""
        msg_lower = message.lower()
        zone_names = zone_names or []

        if len(zone_names) >= 2 and any(kw in msg_lower for kw in REPORT_TYPES["comparison_report"]["keywords"]):
            return {
                "type": "comparison_report",
                "confidence": 0.95,
                "method": "keywords_comparison"
            }

        # Verificar si el mensaje pide un reporte
        report_intent = any(kw in msg_lower for kw in [
            "reporte", "informe", "report", "genera", "generar", "pdf", "descargar"
        ])

        if not report_intent:
            return None

        # Clasificar por keywords del tipo
        best_match = None
        best_score = 0

        for report_type, config in REPORT_TYPES.items():
            score = sum(1 for kw in config["keywords"] if kw in msg_lower)

            # Bonus por capas activas que coincidan
            for layer in active_layers:
                layer_lower = layer.lower()
                for kw in config["keywords"]:
                    if kw in layer_lower:
                        score += 2

            if score > best_score:
                best_score = score
                best_match = report_type

        if best_match and best_score > 0:
            return {
                "type": best_match,
                "confidence": min(best_score / 5.0, 0.95),
                "method": "keywords"
            }

        # Si hay intención de reporte pero no se pudo clasificar, usar general
        if report_intent:
            return {
                "type": "general_report",
                "confidence": 0.5,
                "method": "keywords_fallback"
            }

        return None

    async def classify_with_llm(
        self,
        message: str,
        active_layers: List[str],
        zone_names: Optional[List[str]] = None,
        model_id: str = "gemini-2.0-flash"
    ) -> Dict[str, Any]:
        """Clasificación precisa usando el LLM."""
        try:
            types_desc = "\n".join([
                f"- {key}: {val['description']}"
                for key, val in REPORT_TYPES.items()
            ])

            prompt = f"""Clasifica el siguiente mensaje del usuario en UNO de estos tipos de reporte:

{types_desc}

Capas activas en el mapa del usuario: {', '.join(active_layers) if active_layers else 'Ninguna'}
Zonas detectadas: {', '.join(zone_names or []) if zone_names else 'Ninguna'}

Mensaje del usuario: "{message}"

Responde SOLO con JSON (sin markdown):
{{"type": "<tipo_reporte>", "confidence": <0.0-1.0>}}"""

            client = LLMProviderFactory.create("google", settings.GOOGLE_API, model_id)
            response = await client.chat_complete(
                messages=[Message(role="user", content=prompt)]
            )

            if response.get("status") == "success":
                content = response["message"]["content"].strip()
                # Limpiar posibles bloques de código markdown
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                result = json.loads(content)
                result["method"] = "llm"
                return result

        except Exception as e:
            logger.error(f"Error en clasificación LLM: {e}")

        return {"type": "general_report", "confidence": 0.3, "method": "fallback"}

    async def classify(self, message: str, active_layers: List[str], zone_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Clasificación combinada: intenta keywords primero, LLM si no es concluyente.
        """
        # Intento rápido por keywords
        result = self.classify_by_keywords(message, active_layers, zone_names)

        if result and result["confidence"] >= 0.6:
            return result

        # Si keywords no fue concluyente, usar LLM
        llm_result = await self.classify_with_llm(message, active_layers, zone_names)

        # Combinar confianza si keywords dio algo
        if result and llm_result["type"] == result["type"]:
            llm_result["confidence"] = min(
                (result["confidence"] + llm_result["confidence"]) / 1.5,
                0.98
            )

        return llm_result
