"""
GeoMaps — Intérprete de Reportes.
Usa el LLM para generar texto de análisis profesional a partir de datos espaciales.
"""
import logging
import json
from typing import Any, Dict
from app.shared.core.config import settings
from app.infrastructure.ia_llm_client import LLMProviderFactory
from app.schemas.ia import Message

logger = logging.getLogger(__name__)


class ReportInterpreter:
    """
    Genera texto interpretativo profesional para la sección "Interpretación IA" del reporte.
    """

    REPORT_TYPE_CONTEXT = {
        "cadastral_report": "análisis catastral de predios, propiedades y distribución territorial",
        "hydrology_report": "análisis hidrológico, evaluación de riesgo de inundación y gestión de cuencas",
        "general_report": "análisis geoespacial general de las capas disponibles en la zona",
    }

    async def interpret(
        self,
        spatial_data: Dict[str, Any],
        report_type: str,
        model_id: str = "gemini-2.0-flash"
    ) -> str:
        """
        Genera un texto de interpretación profesional basado en los datos espaciales.
        """
        context = self.REPORT_TYPE_CONTEXT.get(report_type, "análisis geoespacial")

        # Serializar datos relevantes para no saturar el prompt con binarios.
        data_summary = {k: v for k, v in spatial_data.items() if not isinstance(v, bytes)}

        prompt = f"""Eres un analista geoespacial senior redactando la sección de interpretación de un reporte profesional de {context}.

DATOS DEL ANÁLISIS ESPACIAL:
{json.dumps(data_summary, ensure_ascii=False, indent=2, default=str)}

INSTRUCCIONES:
1. Redacta un análisis interpretativo de 3-5 párrafos en español profesional.
2. Menciona hallazgos clave, patrones identificados y recomendaciones.
3. Usa datos exactos del análisis (no inventes números).
4. Tono: técnico-ejecutivo, como un informe profesional de consultoría GIS.
5. NO uses markdown, listas, emojis ni headers. Solo prosa fluida.
6. Si los datos son limitados, indica qué análisis adicionales se recomiendan.
7. Máximo 300 palabras.

Responde SOLO con el texto del análisis, sin encabezados ni formato."""

        try:
            api_key = settings.GOOGLE_API or ""
            client = LLMProviderFactory.create("google", api_key, model_id)
            response = await client.chat_complete(
                messages=[Message(role="user", content=prompt)]
            )

            if response.get("status") == "success":
                return response["message"]["content"].strip()

        except Exception as e:
            logger.error(f"Error generando interpretación: {e}")

        # Fallback: interpretación genérica
        return self._generate_fallback_interpretation(spatial_data, report_type)

    def _generate_fallback_interpretation(
        self,
        spatial_data: Dict[str, Any],
        report_type: str
    ) -> str:
        """Genera una interpretación básica sin LLM cuando el modelo no está disponible."""
        parts = []

        if report_type == "cadastral_report":
            total = spatial_data.get("total_predios", 0)
            parts.append(
                f"El análisis catastral de la zona seleccionada identifica un total de {total} predios "
                f"dentro del área de estudio."
            )

            dist = spatial_data.get("distribution_by_type", [])
            if dist:
                top = dist[0]
                parts.append(
                    f"La categoría predominante es '{top['name']}' con {top['value']} unidades, "
                    f"lo que sugiere un uso territorial mayoritariamente concentrado en esta tipología."
                )

        elif report_type == "hydrology_report":
            risk = spatial_data.get("risk_estimation", {})
            level = risk.get("risk_level", "No determinado")
            parts.append(
                f"La evaluación hidrológica preliminar del área indica un nivel de riesgo de inundación {level}. "
                f"Esta estimación se basa en la proximidad a cuerpos de agua y las características de cobertura del suelo."
            )

        else:
            layers = spatial_data.get("layers_summary", [])
            if layers:
                parts.append(
                    f"El análisis geoespacial de la zona identifica {len(layers)} capas con información relevante. "
                    f"La capa con mayor densidad de datos es '{layers[0]['name']}' con {layers[0]['count']} elementos."
                )

        parts.append(
            "Se recomienda complementar este análisis con datos adicionales de campo para "
            "validar las estimaciones realizadas y refinar las conclusiones del presente informe."
        )

        return " ".join(parts)
