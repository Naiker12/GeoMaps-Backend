import uuid
import asyncio
from app.services.ia.comparison_results import build_zone_comparison
from app.services.ia.runtime_limits import coherent_history, bounded_tool_result, validate_native_calls
from app.services.ia.provider_connections import decrypt_key
import logging
import json
import time
import re
import unicodedata
from uuid import UUID
from typing import List, Dict, Any, Optional, AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.infrastructure.ia_llm_client import LLMProviderFactory
from app.services.ia.prompt_builder import PromptBuilder, extract_suggestions_from_text
from app.services.ia.history_service import HistoryService
from app.services.ia.tools import ToolsService
from app.services.ia.zone_extractor import extract_zone_names
from app.schemas.ia import ChatRequest, ChatResponse, Message, IAModelConfig
from app.core.exceptions import LLMException
from app.services.ia.geo_context import normalize_extent_to_bbox, resolve_geo_context

COMPARISON_KEYWORDS = ["compara", "comparar", "comparacion", "comparación", " vs ", " versus ", "diferencia", "diferencias"]
EXPLICIT_STATS_KEYWORDS = [
    "grafica", "gráfico", "grafico", "estadistica", "estadísticas",
    "distribucion", "distribución", "puestos", "votacion", "votación",
    "colegio", "educacion", "educación", "institucion", "institución",
    "paradero", "ruta",
]

GRAFICO_KEYWORDS = ["gráfico", "grafica", "chart", "visualiza", "barras", "pastel", "pie", "línea", "muéstrame en gráfico"]

def allows_map_changes(message: str) -> bool:
    normalized = ''.join(char for char in unicodedata.normalize('NFD', message.lower()) if not unicodedata.combining(char))
    return not re.search(r"(?:no\s+(?:actives|cambies|modifiques|muevas|toques|alteres|hagas cambios).{0,60}(?:mapa|capas)|sin\s+(?:cambiar|modificar|mover|alterar).{0,30}(?:mapa|capas))", normalized)

def needs_chart_clarification(message: str) -> bool:
    """Retorna True si el usuario quiere un gráfico pero no especificó el tipo."""
    msg_lower = message.lower()
    has_chart_intent = any(kw in msg_lower for kw in GRAFICO_KEYWORDS)
    chart_prefs_complete = "barras" in msg_lower or "pastel" in msg_lower or "línea" in msg_lower or "pie" in msg_lower
    return has_chart_intent and not chart_prefs_complete

def is_comparison_request(message: str) -> bool:
    msg_lower = f" {message.lower()} "
    return any(keyword in msg_lower for keyword in COMPARISON_KEYWORDS)

def should_expose_tool_visual(message: str, layer_name: Optional[str], tool_name: str) -> bool:
    msg_lower = f" {message.lower()} "
    layer_lower = (layer_name or "").lower()
    if not is_comparison_request(message):
        return True
    if tool_name not in {"consultar_estadisticas_capa", "consultar_datos_tabla"}:
        return True
    if any(keyword in msg_lower for keyword in EXPLICIT_STATS_KEYWORDS):
        return True
    if layer_lower and layer_lower in msg_lower:
        return True
    return False

logger = logging.getLogger(__name__)


def _pick_prop(props: Dict[str, Any], tokens: List[str]) -> str:
    for key, value in (props or {}).items():
        normalized_key = str(key).lower()
        if any(token in normalized_key for token in tokens):
            if value not in (None, ""):
                return str(value)
    return "No disponible con las capas actuales"

class AgentService:
    def __init__(self, db: AsyncSession, model_config: Optional[IAModelConfig] = None):
        self.db = db
        self.model_config = model_config
        self.prompt_builder = PromptBuilder()
        self.history_service = HistoryService(db)
        self.tools_service = ToolsService(db)

    async def _get_model_config(self, model_id: str) -> Optional[IAModelConfig]:
        """Obtiene la configuración del modelo desde la base de datos."""
        stmt = text("""
            SELECT id, name, provider, model_id, is_active, base_url, api_key_encrypted, is_default,
                   input_cost_per_1k, output_cost_per_1k,
                   has_function_calling, has_vision, max_context_tokens
            FROM ia_models_config
            WHERE (model_id = :mid OR id::text = :mid) AND is_active = true
            ORDER BY (id::text = :mid) DESC, is_default DESC, name ASC
            LIMIT 1
        """)
        result = await self.db.execute(stmt, {"mid": model_id})
        row = result.mappings().one_or_none()
        if not row:
            return None

        d = dict(row)
        # Convertir decimal a float para compatibilidad con Pydantic
        if d.get("input_cost_per_1k") is not None: d["input_cost_per_1k"] = float(d["input_cost_per_1k"])
        if d.get("output_cost_per_1k") is not None: d["output_cost_per_1k"] = float(d["output_cost_per_1k"])

        return IAModelConfig.model_validate(d)


    async def _get_any_active_model(self) -> Optional[IAModelConfig]:
        """Obtiene el primer modelo activo disponible."""
        stmt = text("""
            SELECT id, name, provider, model_id, is_active, base_url, api_key_encrypted, is_default,
                   input_cost_per_1k, output_cost_per_1k,
                   has_function_calling, has_vision, max_context_tokens
            FROM ia_models_config
            WHERE is_active = true
            ORDER BY is_default DESC, name ASC
            LIMIT 1
        """)
        result = await self.db.execute(stmt)
        row = result.mappings().one_or_none()
        if not row:
            return None

        d = dict(row)
        if d.get("input_cost_per_1k") is not None: d["input_cost_per_1k"] = float(d["input_cost_per_1k"])
        if d.get("output_cost_per_1k") is not None: d["output_cost_per_1k"] = float(d["output_cost_per_1k"])

        return IAModelConfig.model_validate(d)


    async def get_available_models(self) -> List[IAModelConfig]:
        """Obtiene todos los modelos activos disponibles."""
        stmt = text("""
            SELECT id, name, provider, model_id, is_active, base_url, api_key_encrypted, is_default,
                   input_cost_per_1k, output_cost_per_1k,
                   has_function_calling, has_vision, max_context_tokens
            FROM ia_models_config
            WHERE is_active = true
            ORDER BY is_default DESC, name ASC
        """)
        result = await self.db.execute(stmt)
        models = []
        for row in result.mappings().all():
            try:
                d = dict(row)
                if d.get("input_cost_per_1k") is not None: d["input_cost_per_1k"] = float(d["input_cost_per_1k"])
                if d.get("output_cost_per_1k") is not None: d["output_cost_per_1k"] = float(d["output_cost_per_1k"])
                models.append(IAModelConfig.model_validate(d))
            except Exception as e:
                logger.error(f"Error parsing model config: {e}")
        return models


    async def _get_available_layers(self) -> List[Dict[str, Any]]:
        result = await self.tools_service.listar_capas_disponibles()
        return result.get("layers", [])

    async def _find_barrio_feature(self, zone_name: str) -> Optional[Dict[str, Any]]:
        stmt = text("""
            SELECT
                l.name AS layer_name,
                lf.properties AS properties,
                ST_AsGeoJSON(lf.geom) AS geom
            FROM public.layers l
            JOIN public.layer_features lf ON l.id = lf.layer_id
            WHERE l.visibility = 'PUBLIC'
              AND (
                unaccent(LOWER(l.name)) LIKE '%barrio%'
                OR unaccent(LOWER(l.name)) LIKE '%sector%'
                OR unaccent(LOWER(l.name)) LIKE '%zona%'
              )
              AND EXISTS (
                SELECT 1
                FROM jsonb_each_text(lf.properties) AS kv(key, value)
                WHERE unaccent(LOWER(kv.value)) ILIKE unaccent(LOWER(:zone))
              )
            ORDER BY
              CASE
                WHEN unaccent(LOWER(l.name)) LIKE '%barrio%' THEN 0
                WHEN unaccent(LOWER(l.name)) LIKE '%sector%' THEN 1
                ELSE 2
              END
            LIMIT 1
        """)
        result = await self.db.execute(stmt, {"zone": f"%{zone_name}%"})
        row = result.mappings().one_or_none()
        if not row:
            return None
        return {
            "name": zone_name,
            "layer_name": str(row["layer_name"]),
            "properties": row["properties"] or {},
            "geometry": json.loads(row["geom"]) if row["geom"] else None,
        }

    async def _try_fast_zone_comparison(
        self,
        request: ChatRequest,
        conv_id: UUID,
        model_name: str,
        start_time: float,
    ) -> Optional[ChatResponse]:
        if not is_comparison_request(request.message):
            return None

        zones = extract_zone_names(request.message)
        if len(zones) < 2:
            return None

        found = []
        missing = []
        for zone in zones[:4]:
            feature = await self._find_barrio_feature(zone)
            if feature:
                found.append(feature)
            else:
                missing.append(zone)

        if len(found) < 2:
            return None

        map_actions = [{
            "map_action": "highlight_zones",
            "layer_name": found[0]["layer_name"],
            "zones": [
                {
                    "name": item["name"],
                    "geometry": item["geometry"],
                    "properties": item["properties"],
                }
                for item in found
            ],
        }]

        rows = [
            ("Capa delimitadora", [item["layer_name"] for item in found]),
            ("Localidad", [_pick_prop(item["properties"], ["localidad", "locali"]) for item in found]),
            ("Unidad Comunera / UCG", [_pick_prop(item["properties"], ["ucg", "comuna", "comuner"]) for item in found]),
            ("Área", [_pick_prop(item["properties"], ["area", "hect", "superficie"]) for item in found]),
            ("Perímetro", [_pick_prop(item["properties"], ["perimet", "perímet"]) for item in found]),
        ]

        header = "| Variable | " + " | ".join(item["name"] for item in found) + " |"
        separator = "|---|" + "|".join("---" for _ in found) + "|"
        table_lines = [header, separator]
        for label, values in rows:
            table_lines.append("| " + label + " | " + " | ".join(values) + " |")

        limitations = []
        if missing:
            limitations.append(f"No encontré estas zonas en la capa de barrios: {', '.join(missing)}.")
        limitations.append(
            "No se calcularon capas temáticas adicionales porque la solicitud fue una comparación general de barrios; "
            "si quieres variables concretas como votación, educación, paraderos o rutas, puedo compararlas por separado."
        )

        message = (
            f"He localizado y resaltado {', '.join(item['name'] for item in found)} con colores distintos.\n\n"
            "### Tabla comparativa\n"
            + "\n".join(table_lines)
            + "\n\n### Limitaciones\n"
            + "\n".join(f"- {item}" for item in limitations)
        )

        await self.history_service.save_message(conv_id, "user", request.message)
        await self.history_service.save_message(
            conv_id,
            "assistant",
            message,
            metadata={"map_actions": map_actions, "fast_path": "zone_comparison"},
        )

        return ChatResponse(
            message=message,
            conversation_id=conv_id,
            model_used=model_name,
            latency_ms=int((time.time() - start_time) * 1000),
            tools_called=["fast_zone_comparison"],
            map_actions=map_actions,
            suggestions=[
                "Comparar paraderos entre estos barrios",
                "Generar reporte PDF comparativo",
                "Comparar instituciones educativas",
            ],
        )

    async def _get_or_create_conversation(self, request: ChatRequest, user: Any, model_config: IAModelConfig):
        if request.conversation_id:
            result = await self.db.execute(
                text("SELECT id FROM ia_conversations WHERE id = :cid AND user_id = :uid"),
                {"cid": request.conversation_id, "uid": user.id},
            )
            if result.fetchone():
                return request.conversation_id
        return await self.history_service.create_conversation(
            user_id=user.id, title=request.message[:50] + "...", model_id=model_config.model_id,
        )

    async def chat(self, request: ChatRequest, user: Any) -> ChatResponse:
        start_time = time.time()
        request_id = request.request_id or str(uuid.uuid4())

        model_config = await self._get_model_config(request.model)
        if request.model and not model_config:
            raise LLMException(message="Ese modelo no está disponible. Selecciona otro.", status_code=422, code="MODEL_UNAVAILABLE")
        if not model_config:
            model_config = await self._get_any_active_model()
            if not model_config:
                raise ValueError("No hay modelos de IA activos disponibles en el sistema.")

        conv_id = await self._get_or_create_conversation(request, user, model_config)

        fast_response = None
        if allows_map_changes(request.message):
            fast_response = await self._try_fast_zone_comparison(request, conv_id, model_config.name, start_time)
        if fast_response:
            return fast_response

        history = await self.history_service.get_trimmed_history(conv_id, user.id, max_messages=10)
        conversation_summary = await self.history_service.get_conversation_summary(conv_id)

        available_layers = await self._get_available_layers()
        geo = resolve_geo_context(request.context_mapa, request.geo_context)
        active_zone = geo["active_zone"]
        conversation_layers = geo["conversation_layers"]
        applied_filters = geo["applied_filters"]
        bbox = geo["bbox"]
        self._current_filter = (request.context_mapa or {}).get("active_filter")
        self._analysis_zones = geo["compared_zones"] + ([geo["active_zone"]] if isinstance(geo["active_zone"], dict) else [])
        self._analysis_bbox = bbox
        self._analysis_zone_geometry = active_zone.get("geometry") if isinstance(active_zone, dict) else None
        system_prompt = self.prompt_builder.build_system_prompt(
            bbox=bbox,
            active_layers=[l["name"] for l in request.context_mapa.get("layers", [])] if request.context_mapa and request.context_mapa.get("layers") else None,
            available_layers=available_layers,
            user_name=user.full_name or user.email,
            conversation_summary=conversation_summary,
            active_zone=active_zone,
            conversation_layers=conversation_layers,
            compared_zones=geo["compared_zones"],
            applied_filters=applied_filters,
        )

        messages = [{"role": "system", "content": system_prompt}]

        # Sanitizar historial para Gemini (Evitar INVALID_ARGUMENT en turnos de herramientas)
        sanitized_history = []
        for i, msg in enumerate(history if history else []):
            # Si es un mensaje de asistente con tool_calls
            has_tool_calls = isinstance(msg.metadata, dict) and msg.metadata.get("tool_calls")

            if has_tool_calls:
                # Verificar si el siguiente mensaje es la respuesta de la herramienta
                next_is_tool = (i + 1 < len(history)) and history[i+1].role == "tool"

                # Si no hay respuesta de herramienta después, quitamos las tool_calls de este mensaje
                # para que Gemini no se queje de que falta el turno de respuesta.
                if not next_is_tool:
                    msg.metadata = {k: v for k, v in msg.metadata.items() if k != "tool_calls"}

            # Si es un mensaje de herramienta 'huerfano' (sin el mensaje del asistente previo), lo saltamos
            if msg.role == "tool" and (not sanitized_history or not sanitized_history[-1].get("tool_calls")):
                continue

            sanitized_history.append({
                "role": msg.role,
                "content": msg.content,
                "tool_calls": msg.metadata.get("tool_calls") if isinstance(msg.metadata, dict) else None,
                "tool_call_id": msg.tool_call_id
            })

        # Regla de oro de Gemini: El último mensaje antes de un nuevo mensaje de usuario
        # NO puede ser un mensaje del asistente con tool_calls pendientes.
        if sanitized_history and sanitized_history[-1].get("tool_calls"):
             sanitized_history[-1]["tool_calls"] = None

        messages.extend(coherent_history(sanitized_history, min(40000, (model_config.max_context_tokens or 4096) * 2)))

        user_metadata = {'geo_context': request.geo_context, 'context_mapa': request.context_mapa}

        messages.append({"role": "user", "content": request.message, "metadata": user_metadata})

        await self.history_service.save_message(conv_id, "user", request.message, metadata=user_metadata)
        await self.db.commit()

        client = LLMProviderFactory.create(model_config.provider.lower(), decrypt_key(model_config.api_key_encrypted), model_config.model_id, model_config.base_url)
        client.max_output_tokens = min(4096, max(256, (model_config.max_context_tokens or 4096) // 4))
        tools = await self.tools_service.get_tools_metadata() if model_config.has_function_calling else []

        total_tokens_in = 0
        total_tokens_out = 0
        map_actions = []
        tools_called = []
        analytics_data = None
        analysis_results = []
        executed_tool_calls = []

        try:
            response = await client.chat_complete(
                messages=[Message(**m) for m in messages],
                tools=tools if tools else None,
            )

            if response.get("status") == "error":
                raise LLMException(
                    message=response.get("error_message", "Error Desconocido"),
                    status_code=response.get("status_code", 500),
                    code=response.get("error_code", "LLM_ERROR")
                )

            total_tokens_in += response.get("tokens_input", 0)
            total_tokens_out += response.get("tokens_output", 0)
            msg = response["message"]

            iterations = 0
            while msg.get("tool_calls") and iterations < 3:
                iterations += 1
                msg["metadata"] = {**(msg.get("metadata") or {}), "model": model_config.model_id}
                messages.append(msg)
                await self.history_service.save_message(
                    conv_id, "assistant", msg.get("content") or "",
                    metadata={"model":model_config.model_id,"tool_calls":msg.get("tool_calls")}
                )

                validate_native_calls(msg["tool_calls"], tools)
                for tcall in msg["tool_calls"]:
                    func_name = tcall["function"]["name"]
                    func_args = json.loads(tcall["function"]["arguments"])
                    tool_result = await asyncio.wait_for(self._execute_tool(func_name, func_args), timeout=30)
                    tools_called.append(func_name)
                    executed_tool_calls.append({
                        "id": tcall.get("id"),
                        "type": tcall.get("type", "function"),
                        "function": {
                            "name": func_name,
                            "arguments": json.dumps(func_args, ensure_ascii=False),
                        },
                        "success": bool(isinstance(tool_result, dict) and tool_result.get("success", True)),
                    })

                    expose_tool_visual = should_expose_tool_visual(
                        request.message,
                        func_args.get("layer_name") if isinstance(func_args, dict) else None,
                        func_name,
                    )

                    if isinstance(tool_result, dict):
                        if tool_result.get("success", True) and isinstance(tool_result.get("analysis"), dict):
                            analysis_results.append(tool_result["analysis"])
                        if allows_map_changes(request.message) and expose_tool_visual and tool_result.get("map_action"): map_actions.append(tool_result)
                        if allows_map_changes(request.message) and expose_tool_visual and tool_result.get("map_actions"):
                            for action in tool_result["map_actions"]:
                                if "type" in action and "map_action" not in action:
                                    action["map_action"] = action.pop("type")
                                map_actions.append(action)
                        if expose_tool_visual and tool_result.get("analytics_data"): analytics_data = tool_result.get("analytics_data")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tcall["id"],
                        "name": func_name,
                        "content": bounded_tool_result(tool_result)
                    })
                    await self.history_service.save_message(
                        conv_id, "tool", json.dumps(tool_result),
                        tool_call_id=tcall["id"], metadata={"function": func_name}
                    )

                response = await client.chat_complete(
                    messages=[Message(**m) for m in messages],
                    tools=tools if tools else None
                )
                if response.get("status") == "error":
                    raise LLMException(
                        message="Error Desconocido",
                        status_code=response.get("status_code", 500),
                        code=response.get("error_code", "LLM_ERROR")
                    )

                total_tokens_in += response.get("tokens_input", 0)
                total_tokens_out += response.get("tokens_output", 0)
                msg = response["message"]

            if is_comparison_request(request.message): analytics_data = build_zone_comparison(analysis_results)
            if msg.get("tool_calls"):
                raise LLMException(message="Se alcanzó el límite de herramientas. Reduce el alcance de la consulta.", status_code=422, code="TOOL_BUDGET_EXCEEDED")
            final_response_content = msg.get("content") or ""
            await self.history_service.save_message(
                conv_id, "assistant", final_response_content,
                metadata={
                    "model": model_config.model_id,
                    "request_id": request_id,
                    "map_actions": map_actions,
                    "analysis_results": analysis_results, "analytics_data": analytics_data
                }
            )

            latency_ms = int((time.time() - start_time) * 1000)
            cost = (total_tokens_in * (model_config.input_cost_per_1k or 0.0) / 1000) + \
                   (total_tokens_out * (model_config.output_cost_per_1k or 0.0) / 1000)

            await self._save_audit_log(user.id, conv_id, model_config.name, total_tokens_in, total_tokens_out, cost, latency_ms)

            return ChatResponse(
                message=final_response_content,
                conversation_id=conv_id,
                model_used=model_config.name,
                tokens_input=total_tokens_in,
                tokens_output=total_tokens_out,
                cost=cost,
                latency_ms=latency_ms,
                tools_called=tools_called,
                tools_called_raw=executed_tool_calls,
                map_actions=map_actions,
                analytics_data=analytics_data,
                analysis_results=analysis_results,
            )
        except Exception as e:
            logger.error(f"Error en AgentService.chat: {e}")
            raise e

    async def chat_stream(self, request: ChatRequest, user: Any) -> AsyncGenerator[str, None]:
        """Generador SSE para streaming de chat con Gemini 2.0 (Soporta Tool Calls)."""
        start_time = time.time()

        model_config = await self._get_model_config(request.model)
        if request.model and not model_config:
            yield f"data: {json.dumps({'type':'error','content':'Ese modelo no está disponible. Selecciona otro.'})}\n\n"
            return
        if not model_config:
            model_config = await self._get_any_active_model()
            if not model_config:
                yield f"data: {json.dumps({'type': 'error', 'content': 'No hay modelos activos'})}\n\n"
                return

        conv_id = await self._get_or_create_conversation(request, user, model_config)

        history = await self.history_service.get_trimmed_history(conv_id, user.id, max_messages=10)
        conversation_summary = await self.history_service.get_conversation_summary(conv_id)

        available_layers = await self._get_available_layers()
        geo = resolve_geo_context(request.context_mapa, request.geo_context)
        bbox = geo["bbox"]
        self._current_filter = (request.context_mapa or {}).get("active_filter")
        self._analysis_zones = geo["compared_zones"] + ([geo["active_zone"]] if isinstance(geo["active_zone"], dict) else [])
        self._analysis_bbox = bbox
        self._analysis_zone_geometry = geo["active_zone"].get("geometry") if isinstance(geo["active_zone"], dict) else None
        system_prompt = self.prompt_builder.build_system_prompt(
            bbox=bbox,
            active_layers=[l["name"] for l in request.context_mapa.get("layers", [])] if request.context_mapa and request.context_mapa.get("layers") else None,
            available_layers=available_layers,
            user_name=user.full_name or user.email,
            conversation_summary=conversation_summary,
            active_zone=geo["active_zone"],
            conversation_layers=geo["conversation_layers"],
            compared_zones=geo["compared_zones"],
            applied_filters=geo["applied_filters"],
        )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(coherent_history([{"role": msg.role, "content": msg.content,
            "tool_call_id": msg.tool_call_id, "metadata": msg.metadata} for msg in history or []], min(40000, (model_config.max_context_tokens or 4096) * 2)))
        user_metadata = {'geo_context': request.geo_context, 'context_mapa': request.context_mapa}

        messages.append({"role": "user", "content": request.message, "metadata": user_metadata})

        await self.history_service.save_message(conv_id, "user", request.message, metadata=user_metadata)
        await self.db.commit()

        client = LLMProviderFactory.create(model_config.provider.lower(), decrypt_key(model_config.api_key_encrypted), model_config.model_id, model_config.base_url)
        client.max_output_tokens = min(4096, max(256, (model_config.max_context_tokens or 4096) // 4))
        tools = await self.tools_service.get_tools_metadata() if model_config.has_function_calling else []

        request_id = request.request_id or str(uuid.uuid4())
        yield f"data: {json.dumps({'type': 'start', 'conversation_id': str(conv_id), 'request_id': request_id, 'model_used': model_config.name})}\n\n"
        self._stream_run = {"conversation_id": conv_id, "user_id": user.id, "model": model_config.name,
                            "start_time": start_time, "request_id": request_id, "partial": "", "tokens_input": 0, "tokens_output": 0}
        self._stream_failure_saved = False
        executed_tool_calls = []
        full_content = ""
        total_tokens_in = 0
        total_tokens_out = 0
        map_actions = []
        analytics_data = None
        analysis_results = []

        iterations = 0
        max_iterations = 3

        while iterations < max_iterations:
            iterations += 1
            if time.time() - start_time > 150:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Se alcanzó el límite de tiempo. Reduce el alcance de la consulta.'})}\n\n"
                return
            has_tool_calls = False
            current_tool_calls = []

            async for chunk in client.chat_stream(messages=[Message(**m) for m in messages], tools=tools if tools and iterations < max_iterations else None):
                if chunk["type"] == "text":
                    full_content += chunk["content"]
                    self._stream_run["partial"] = full_content
                    yield f"data: {json.dumps({'type': 'text', 'content': chunk['content'], 'conversation_id': str(conv_id)})}\n\n"

                elif chunk["type"] == "tool_call":
                    has_tool_calls = True
                    try:
                        validate_native_calls(chunk["tool_calls"], tools if iterations < max_iterations else [])
                    except ValueError:
                        yield f"data: {json.dumps({'type': 'error', 'content': 'El modelo solicitó una herramienta inválida. Prueba con otro modelo.'})}\n\n"
                        return
                    for tcall in chunk["tool_calls"]:
                        current_tool_calls.append(tcall)
                        func_name = tcall["function"]["name"]
                        yield f"data: {json.dumps({'type': 'tool_status', 'tool_name': func_name, 'tool_call_id': tcall['id']})}\n\n"

                elif chunk["type"] == "error":
                    await self.record_stream_failure("error")
                    yield f"data: {json.dumps({'type': 'error', 'content': chunk['content']})}\n\n"
                    return

                elif chunk["type"] == "done":
                    total_tokens_in += chunk.get("tokens_input", 0)
                    total_tokens_out += chunk.get("tokens_output", 0)
                    self._stream_run.update(tokens_input=total_tokens_in, tokens_output=total_tokens_out)

            if not has_tool_calls:
                break

            try:
                validate_native_calls(current_tool_calls, tools)
            except ValueError:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Se alcanzó el límite de herramientas por turno.'})}\n\n"
                return
            # Si hubo tool calls, procesarlas y reanudar
            # Guardar el mensaje del asistente con los tool_calls
            assistant_msg = {
                "role": "assistant",
                "content": full_content,
                "metadata": {"model":model_config.model_id,"tool_calls":current_tool_calls}
            }
            messages.append(assistant_msg)
            await self.history_service.save_message(
                conv_id, "assistant", full_content,
                metadata={"model":model_config.model_id,"tool_calls":current_tool_calls}
            )
            full_content = "" # Limpiar para la siguiente vuelta si el modelo sigue hablando

            # Ejecutar herramientas y agregar respuestas
            for tcall in current_tool_calls:
                func_name = tcall["function"]["name"]
                func_args = json.loads(tcall["function"]["arguments"])

                tool_result = await asyncio.wait_for(self._execute_tool(func_name, func_args), timeout=30)
                executed_tool_calls.append({key:value for key,value in tcall.items() if key in ('id','type','function')})
                success = not isinstance(tool_result, dict) or tool_result.get('success', tool_result.get('found', not tool_result.get('error')))
                analysis = tool_result.get('analysis') or {} if isinstance(tool_result, dict) else {}
                evidence = {key: tool_result.get(key, analysis.get(key)) for key in ('source', 'layer', 'scope', 'count', 'updated_at')} if isinstance(tool_result, dict) else {}
                if isinstance(analysis, dict) and evidence.get('count') is None: evidence['count'] = analysis.get('total_features')
                retrieved_sources = [{key: source.get(key) for key in ('id','title','source','updated_at')} for source in tool_result.get('sources', [])[:5]] if isinstance(tool_result, dict) else []
                yield f"data: {json.dumps({'type': 'tool_result', 'request_id': request_id, 'tool_name': func_name, 'tool_call_id': tcall['id'], 'success': success, 'evidence': evidence, 'retrieved_sources': retrieved_sources, 'detail': 'Consulta completada' if success else 'La consulta no se completó'})}\n\n"

                expose_tool_visual = should_expose_tool_visual(
                    request.message,
                    func_args.get("layer_name") if isinstance(func_args, dict) else None,
                    func_name,
                )

                if isinstance(tool_result, dict):
                    if tool_result.get("success", True) and isinstance(tool_result.get("analysis"), dict):
                        analysis_results.append(tool_result["analysis"])
                    if allows_map_changes(request.message) and expose_tool_visual and tool_result.get("map_action"): map_actions.append(tool_result)
                    if allows_map_changes(request.message) and expose_tool_visual and tool_result.get("map_actions"): map_actions.extend(tool_result["map_actions"])
                    if expose_tool_visual and tool_result.get("analytics_data"): analytics_data = tool_result.get("analytics_data")

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tcall["id"],
                    "content": bounded_tool_result(tool_result),
                    "metadata": {"function": func_name}
                }
                messages.append(tool_msg)
                await self.history_service.save_message(
                    conv_id, "tool", tool_msg["content"],
                    tool_call_id=tcall["id"], metadata=tool_msg["metadata"]
                )

        if is_comparison_request(request.message): analytics_data = build_zone_comparison(analysis_results)

        # Guardar la respuesta final (solo si no fue una respuesta vacía tras tools)
        suggestions = []
        if full_content:
            extracted_text, suggestions = extract_suggestions_from_text(full_content)
            await self.history_service.save_message(
                conv_id, "assistant", extracted_text,
                metadata={
                    "model": model_config.model_id,
                    "request_id": request_id,
                    "map_actions": map_actions,
                    "analysis_results": analysis_results, "analytics_data": analytics_data,
                    "suggestions": suggestions
                }
            )

        latency_ms = int((time.time() - start_time) * 1000)
        cost = (total_tokens_in * (model_config.input_cost_per_1k or 0.0) / 1000) + \
               (total_tokens_out * (model_config.output_cost_per_1k or 0.0) / 1000)

        await self._save_audit_log(user.id, conv_id, model_config.name, total_tokens_in, total_tokens_out, cost, latency_ms)

        self._stream_run["complete"] = True
        yield f"data: {json.dumps({'type': 'done', 'request_id': request_id, 'conversation_id': str(conv_id), 'message': extracted_text if full_content else '', 'tools_called_raw': executed_tool_calls, 'map_actions': map_actions, 'analysis_results': analysis_results, 'analytics_data': analytics_data, 'suggestions': suggestions, 'tokens_input': total_tokens_in, 'tokens_output': total_tokens_out, 'cost': cost})}\n\n"

    async def record_stream_failure(self, status="error"):
        run = getattr(self, "_stream_run", None)
        if not run or run.get("complete") or getattr(self, "_stream_failure_saved", False):
            return
        await self.db.rollback()
        notice = "Generación detenida; respuesta incompleta." if status == "cancelled" else "La respuesta se interrumpió; puedes reintentar."
        await self.history_service.save_message(run["conversation_id"], "assistant", run["partial"][:32000] or notice,
            metadata={"generation_status": status, "response_notice": notice, "request_id": run["request_id"]})
        await self._save_audit_log(run["user_id"], run["conversation_id"], run["model"], run["tokens_input"], run["tokens_output"], 0,
                                   int((time.time()-run["start_time"])*1000), status=status)
        self._stream_failure_saved = True

    async def _execute_tool(self, name: str, args: dict) -> Any:
        try:
            if not isinstance(args, dict) or len(json.dumps(args)) > 100000:
                return {"success": False, "code": "INVALID_TOOL_ARGUMENTS", "error": "Argumentos inválidos o demasiado extensos"}
            args = dict(args)
            selected_zone_name = args.pop("zone_name", None)
            if selected_zone_name:
                if args.get("scope") == "entire_layer": raise ValueError("Selecciona toda la capa o una zona, no ambos alcances")
                normalize_name = lambda value: ''.join(char for char in unicodedata.normalize('NFD', str(value).strip().casefold()) if not unicodedata.combining(char))
                matches = [zone for zone in getattr(self, "_analysis_zones", []) if normalize_name(zone.get("name")) == normalize_name(selected_zone_name)]
                if len(matches) != 1 or not matches[0].get("geometry"):
                    return {"success": False, "needs_clarification": True, "error": "Selecciona una zona ya localizada con límites conocidos", "candidates": [zone.get("name") for zone in getattr(self, "_analysis_zones", [])]}
                args["zone_geometry"] = matches[0]["geometry"]
                selected_zone_name = matches[0]["name"]
            if "layer_name" in args:
                resolved = await self.tools_service.resolve_public_layer(args["layer_name"], args.get("layer_id"))
                if not resolved.get("success"):
                    return resolved
                args["layer_name"] = resolved["layer"]["name"]
            if name == "listar_capas_disponibles": return await self.tools_service.listar_capas_disponibles(**args)
            if name == "buscar_conocimiento_capas": return await self.tools_service.buscar_conocimiento_capas(**args)
            if name == "analizar_capa_geografica" and args.get("scope") != "entire_layer" and args.get("coordinates") is None and args.get("zone_geometry") is None and getattr(self, "_analysis_zone_geometry", None) is not None:
                args["zone_geometry"] = self._analysis_zone_geometry
            if name in {"consultar_registros_capa", "consultar_datos_tabla", "consultar_estadisticas_capa", "consultar_predios"} and args.get("scope") != "entire_layer" and args.get("bbox") is None and args.get("zone_geometry") is None and getattr(self, "_analysis_zone_geometry", None) is not None:
                args["zone_geometry"] = self._analysis_zone_geometry
            if name in {"analizar_capa_geografica", "analizar_zona_extent", "consultar_estadisticas_capa", "consultar_datos_tabla", "consultar_registros_capa", "consultar_predios"} and args.get("bbox") is None and args.get("scope") != "entire_layer" and args.get("coordinates") is None:
                if getattr(self, "_analysis_bbox", None) is not None and not (name == "analizar_capa_geografica" and args.get("zone_geometry") is not None):
                    args["bbox"] = list(self._analysis_bbox)
            if name in {"consultar_datos_tabla", "consultar_estadisticas_capa", "consultar_registros_capa"} and args.get("scope") != "entire_layer":
                current_filter = getattr(self, "_current_filter", None)
                if isinstance(current_filter, dict) and args.get("filter_field") is None:
                    args["filter_field"], args["filter_value"] = current_filter.get("key"), current_filter.get("value")
            if name == "consultar_registros_capa": return await self.tools_service.consultar_registros_capa(**args)
            if name == "analizar_capa_geografica":
                result = await self.tools_service.analizar_capa_geografica(**args)
                if selected_zone_name and isinstance(result.get("analysis"), dict): result["analysis"]["zone_name"] = selected_zone_name
                return result
            elif name == "consultar_predios": return await self.tools_service.consultar_predios(**args)
            elif name == "analizar_zona_extent": return await self.tools_service.analizar_zona_extent(**args)
            elif name == "consultar_estadisticas_capa": return await self.tools_service.consultar_estadisticas_capa(**args)
            elif name == "activate_layer": return await self.tools_service.activate_layer(**args)
            elif name == "activate_category": return await self.tools_service.activate_category(**args)
            elif name == "change_basemap": return await self.tools_service.change_basemap(**args)
            elif name == "zoom_to_location": return await self.tools_service.zoom_to_location(**args)
            elif name in {"buscar_y_mostrar_entidad", "buscar_y_mostrar_entidades"}:
                method = getattr(self.tools_service, name)
                result = await method(**args)
                if result.get("success", True):
                    known = []
                    for action in result.get("map_actions", []):
                        if action.get("map_action") == "highlight_zone": known.append({"name":action.get("zone_name") or action.get("label"),"geometry":action.get("geojson"),"bbox":action.get("bbox")})
                        elif action.get("map_action") == "highlight_zones": known.extend(action.get("zones", []))
                    if known:
                        self._analysis_zones = known[:6]
                        if len(known) == 1: self._analysis_zone_geometry = known[0].get("geometry")
                return result
            elif name == "mostrar_ruta_animada": return await self.tools_service.mostrar_ruta_animada(**args)
            elif name == "listar_campos_capa": return await self.tools_service.listar_campos_capa(**args)
            elif name == "consultar_datos_tabla": return await self.tools_service.consultar_datos_tabla(**args)
            else: return {"success": False, "error": "Herramienta no disponible"}
        except (ValueError, TypeError) as exc:
            return {"success": False, "error": str(exc), "code": "INVALID_TOOL_ARGUMENTS"}
        except Exception:
            logger.exception("Falló la herramienta de IA %s", name)
            await self.db.rollback()
            return {"success": False, "error": "No se pudo consultar la información; intenta nuevamente", "code": "TOOL_EXECUTION_FAILED"}

    async def _save_audit_log(self, user_id: UUID, conversation_id: UUID, model_name: str, tokens_in: int, tokens_out: int, cost: float, latency_ms: int, status: str = "success"):
        # Siempre insertamos un nuevo registro para cada turno de chat
        # para que el contador de límites de uso (mensajes por hora) sea preciso.
        stmt_insert = text("""
            INSERT INTO ia_audit_logs (user_id, conversation_id, model, tokens_input, tokens_output, cost, latency_ms, status)
            VALUES (:uid, :cid, :model, :tin, :tout, :cost, :lat, :status)
        """)
        await self.db.execute(stmt_insert, {
            "uid": user_id,
            "cid": conversation_id,
            "model": model_name,
            "tin": tokens_in,
            "tout": tokens_out,
            "cost": cost,
            "lat": latency_ms,
            "status": status
        })
        await self.db.commit()
