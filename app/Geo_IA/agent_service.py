import logging
import json
import time
from uuid import UUID
from typing import List, Dict, Any, Optional, AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.shared.core.config import settings
from app.infrastructure.ia_llm_client import LLMProviderFactory
from app.services.ia.prompt_builder import PromptBuilder, extract_suggestions_from_text
from app.services.ia.history_service import HistoryService
from app.services.ia.tools import ToolsService
from app.services.ia.zone_extractor import extract_zone_names
from app.schemas.ia import ChatRequest, ChatResponse, Message, IAModelConfig
from app.shared.core.exceptions import LLMException

COMPARISON_KEYWORDS = ["compara", "comparar", "comparacion", "comparación", " vs ", " versus ", "diferencia", "diferencias"]
EXPLICIT_STATS_KEYWORDS = [
    "grafica", "gráfico", "grafico", "estadistica", "estadísticas",
    "distribucion", "distribución", "puestos", "votacion", "votación",
    "colegio", "educacion", "educación", "institucion", "institución",
    "paradero", "ruta",
]

GRAFICO_KEYWORDS = ["gráfico", "grafica", "chart", "visualiza", "barras", "pastel", "pie", "línea", "muéstrame en gráfico"]

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

def normalize_extent_to_bbox(extent: Any) -> Optional[List[float]]:
    """Convierte objetos de extensión de ArcGIS serializados por el frontend en una lista bbox [xmin, ymin, xmax, ymax]."""
    if not extent:
        return None
    if isinstance(extent, list) and len(extent) >= 4:
        return [float(extent[0]), float(extent[1]), float(extent[2]), float(extent[3])]
    if isinstance(extent, dict):
        keys = ("xmin", "ymin", "xmax", "ymax")
        if all(extent.get(key) is not None for key in keys):
            return [float(extent[key]) for key in keys]
    return None

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
            SELECT id, name, provider, model_id, is_active, 
                   input_cost_per_1k, output_cost_per_1k, 
                   has_function_calling, has_vision, max_context_tokens
            FROM ia_models_config 
            WHERE (model_id = :mid OR id::text = :mid) AND is_active = true
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
            SELECT id, name, provider, model_id, is_active, 
                   input_cost_per_1k, output_cost_per_1k, 
                   has_function_calling, has_vision, max_context_tokens
            FROM ia_models_config 
            WHERE is_active = true
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
            SELECT id, name, provider, model_id, is_active, 
                   input_cost_per_1k, output_cost_per_1k, 
                   has_function_calling, has_vision, max_context_tokens
            FROM ia_models_config 
            WHERE is_active = true
            ORDER BY name ASC
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
        """Obtiene nombres y metadatos de campos de las capas disponibles."""
        try:
            query = text("""
                SELECT name, stats_config, feature_card_config 
                FROM public.layers 
                WHERE visibility != 'PRIVATE'
            """)
            result = await self.db.execute(query)
            rows = result.fetchall()
            
            layers_metadata = []
            for row in rows:
                name, stats, card = row
                fields = []
                
                if card and isinstance(card, dict) and "sections" in card:
                    for section in card["sections"]:
                        for field in section.get("fields", []):
                            fields.append(f"{field.get('key')} ({field.get('label')})")
                elif stats and isinstance(stats, dict) and "kpis" in stats:
                    for kpi in stats["kpis"]:
                        fields.append(f"{kpi.get('field')} ({kpi.get('label')})")
                
                if not fields:
                    try:
                        sample_query = text("""
                            SELECT properties FROM layer_features 
                            WHERE layer_id = (SELECT id FROM layers WHERE name = :name LIMIT 1) 
                            LIMIT 1
                        """)
                        sample_res = await self.db.execute(sample_query, {"name": name})
                        sample_row = sample_res.scalar()
                        if sample_row and isinstance(sample_row, dict):
                            fields = [f"{k}" for k in list(sample_row.keys())[:8]]
                    except Exception:
                        pass
                
                layers_metadata.append({
                    "name": name,
                    "fields": fields[:12]
                })
            return layers_metadata
        except Exception as e:
            logger.error(f"Error cargando metadatos de capas: {e}")
            return []

    async def _find_barrio_feature(self, zone_name: str) -> Optional[Dict[str, Any]]:
        stmt = text("""
            SELECT
                l.name AS layer_name,
                lf.properties AS properties,
                ST_AsGeoJSON(lf.geom) AS geom
            FROM public.layers l
            JOIN public.layer_features lf ON l.id = lf.layer_id
            WHERE l.visibility != 'PRIVATE'
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

    async def chat(self, request: ChatRequest, user: Any) -> ChatResponse:
        start_time = time.time()
        
        model_config = await self._get_model_config(request.model)
        if not model_config:
            model_config = await self._get_any_active_model()
            if not model_config:
                raise ValueError("No hay modelos de IA activos disponibles en el sistema.")

        conv_id = request.conversation_id
        if conv_id:
            check_exists = await self.db.execute(
                text("SELECT id FROM ia_conversations WHERE id = :cid AND user_id = :uid"),
                {"cid": conv_id, "uid": user.id}
            )
            if not check_exists.fetchone():
                conv_id = None

        if not conv_id:
            conv_id = await self.history_service.create_conversation(
                user_id=user.id, 
                title=request.message[:50] + "...", 
                model_id=model_config.model_id
            )

        fast_response = await self._try_fast_zone_comparison(
            request,
            conv_id,
            model_config.name,
            start_time,
        )
        if fast_response:
            return fast_response

        history = await self.history_service.get_trimmed_history(conv_id, user.id, max_messages=10)
        conversation_summary = await self.history_service.get_conversation_summary(conv_id)
        
        if not conversation_summary and history and len(history) >= 15:
            try:
                summary_prompt = "Resume brevemente los datos y capas analizados en esta conversación para mantener contexto. Sé muy conciso."
                messages_for_summary = [{"role": msg.role, "content": msg.content} for msg in history[-15:] if msg.content and msg.role != "tool"]
                messages_for_summary.append({"role": "user", "content": summary_prompt})
                
                summary_client = LLMProviderFactory.create(model_config.provider.lower(), settings.GOOGLE_API, model_config.model_id)
                summary_response = await summary_client.chat_complete(
                    messages=[Message(**m) for m in messages_for_summary]
                )
                if summary_response.get("status") == "success":
                    new_summary = summary_response["message"]["content"]
                    await self.history_service.save_conversation_summary(conv_id, new_summary)
                    conversation_summary = new_summary
            except Exception as e:
                logger.warning(f"No se pudo generar el resumen automático: {e}")

        if needs_chart_clarification(request.message):
            final_response = "Para preparar tu gráfico, por favor indícame:\n1. ¿Tipo de gráfico? (Barras, Pastel, Línea)\n2. ¿Nivel de detalle? (Resumen, Completo, Por barrio)\n3. ¿Quieres compararlo con otra variable o período?"
            await self.history_service.save_message(conv_id, "user", request.message)
            await self.history_service.save_message(conv_id, "assistant", final_response)
            return ChatResponse(
                message=final_response,
                conversation_id=conv_id,
                model_used=model_config.name,
                latency_ms=0,
                map_actions=[],
                tools_called=[]
            )

        available_layers = await self._get_available_layers()
        geo_context = request.geo_context or {}
        active_zone = geo_context.get("conversation_zone") if isinstance(geo_context, dict) else None
        conversation_layers = geo_context.get("conversation_layers", []) if isinstance(geo_context, dict) else []
        applied_filters = geo_context.get("applied_filters", []) if isinstance(geo_context, dict) else []
        bbox = (
            normalize_extent_to_bbox(active_zone.get("bbox")) if isinstance(active_zone, dict) else None
        ) or normalize_extent_to_bbox(
            geo_context.get("conversation_extent") if isinstance(geo_context, dict) else None
        ) or (
            normalize_extent_to_bbox(request.context_mapa.get("extent")) if request.context_mapa else None
        )
        system_prompt = self.prompt_builder.build_system_prompt(
            bbox=bbox,
            active_layers=[l["name"] for l in request.context_mapa.get("layers", [])] if request.context_mapa and request.context_mapa.get("layers") else None,
            available_layers=available_layers,
            user_name=user.full_name or user.email,
            conversation_summary=conversation_summary,
            active_zone=active_zone,
            conversation_layers=conversation_layers,
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

        messages.extend(sanitized_history)
        
        user_metadata = {}

        messages.append({"role": "user", "content": request.message, "metadata": user_metadata})
        
        await self.history_service.save_message(conv_id, "user", request.message, metadata=user_metadata)

        client = LLMProviderFactory.create(model_config.provider.lower(), settings.GOOGLE_API, model_config.model_id)
        tools = await self.tools_service.get_tools_metadata() if model_config.has_function_calling else []
        
        total_tokens_in = 0
        total_tokens_out = 0
        map_actions = []
        tools_called = []
        analytics_data = None
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
                messages.append(msg)
                await self.history_service.save_message(
                    conv_id, "assistant", msg.get("content") or "", 
                    metadata={"tool_calls": msg.get("tool_calls")}
                )
                
                for tcall in msg["tool_calls"]:
                    func_name = tcall["function"]["name"]
                    func_args = json.loads(tcall["function"]["arguments"])
                    tool_result = await self._execute_tool(func_name, func_args)
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
                        if expose_tool_visual and tool_result.get("map_action"): map_actions.append(tool_result)
                        if expose_tool_visual and tool_result.get("map_actions"):
                            for action in tool_result["map_actions"]:
                                if "type" in action and "map_action" not in action:
                                    action["map_action"] = action.pop("type")
                                map_actions.append(action)
                        if expose_tool_visual and tool_result.get("analytics_data"): analytics_data = tool_result.get("analytics_data")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tcall["id"],
                        "name": func_name,
                        "content": json.dumps(tool_result)
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

            final_response_content = msg.get("content") or ""
            await self.history_service.save_message(
                conv_id, "assistant", final_response_content,
                metadata={
                    "model": model_config.model_id, 
                    "map_actions": map_actions,
                    "analytics_data": analytics_data
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
                analytics_data=analytics_data
            )
        except Exception as e:
            logger.error(f"Error en AgentService.chat: {e}")
            raise e

    async def chat_stream(self, request: ChatRequest, user: Any) -> AsyncGenerator[str, None]:
        """Generador SSE para streaming de chat con Gemini 2.0 (Soporta Tool Calls)."""
        start_time = time.time()
        
        model_config = await self._get_model_config(request.model)
        if not model_config:
            model_config = await self._get_any_active_model()
            if not model_config:
                yield f"data: {json.dumps({'type': 'error', 'content': 'No hay modelos activos'})}\n\n"
                return

        conv_id = request.conversation_id
        if not conv_id:
            conv_id = await self.history_service.create_conversation(
                user_id=user.id, title=request.message[:50] + "...", model_id=model_config.model_id
            )

        history = await self.history_service.get_trimmed_history(conv_id, user.id, max_messages=10)
        conversation_summary = await self.history_service.get_conversation_summary(conv_id)
        
        available_layers = await self._get_available_layers()
        bbox = normalize_extent_to_bbox(request.context_mapa.get("extent")) if request.context_mapa else None
        system_prompt = self.prompt_builder.build_system_prompt(
            bbox=bbox,
            active_layers=[l["name"] for l in request.context_mapa.get("layers", [])] if request.context_mapa and request.context_mapa.get("layers") else None,
            available_layers=available_layers,
            user_name=user.full_name or user.email,
            conversation_summary=conversation_summary
        )

        messages = [{"role": "system", "content": system_prompt}]
        for msg in (history if history else []):
            messages.append({
                "role": msg.role, 
                "content": msg.content, 
                "tool_call_id": msg.tool_call_id,
                "metadata": msg.metadata
            })
        user_metadata = {}

        messages.append({"role": "user", "content": request.message, "metadata": user_metadata})
        
        await self.history_service.save_message(conv_id, "user", request.message, metadata=user_metadata)

        client = LLMProviderFactory.create(model_config.provider.lower(), settings.GOOGLE_API, model_config.model_id)
        tools = await self.tools_service.get_tools_metadata() if model_config.has_function_calling else []

        full_content = ""
        total_tokens_in = 0
        total_tokens_out = 0
        map_actions = []
        analytics_data = None
        
        iterations = 0
        max_iterations = 3
        
        while iterations < max_iterations:
            iterations += 1
            has_tool_calls = False
            current_tool_calls = []

            async for chunk in client.chat_stream(messages=[Message(**m) for m in messages], tools=tools if tools else None):
                if chunk["type"] == "text":
                    full_content += chunk["content"]
                    yield f"data: {json.dumps({'type': 'text', 'content': chunk['content'], 'conversation_id': str(conv_id)})}\n\n"
                
                elif chunk["type"] == "tool_call":
                    has_tool_calls = True
                    for tcall in chunk["tool_calls"]:
                        current_tool_calls.append(tcall)
                        func_name = tcall["function"]["name"]
                        yield f"data: {json.dumps({'type': 'tool_status', 'tool_name': func_name})}\n\n"
                
                elif chunk["type"] == "error":
                    yield f"data: {json.dumps({'type': 'error', 'content': chunk['content']})}\n\n"
                    return
                
                elif chunk["type"] == "done":
                    total_tokens_in += chunk.get("tokens_input", 0)
                    total_tokens_out += chunk.get("tokens_output", 0)

            if not has_tool_calls:
                break
            
            # Si hubo tool calls, procesarlas y reanudar
            # Guardar el mensaje del asistente con los tool_calls
            assistant_msg = {
                "role": "assistant",
                "content": full_content,
                "metadata": {"tool_calls": current_tool_calls}
            }
            messages.append(assistant_msg)
            await self.history_service.save_message(
                conv_id, "assistant", full_content, 
                metadata={"tool_calls": current_tool_calls}
            )
            full_content = "" # Limpiar para la siguiente vuelta si el modelo sigue hablando

            # Ejecutar herramientas y agregar respuestas
            for tcall in current_tool_calls:
                func_name = tcall["function"]["name"]
                func_args = json.loads(tcall["function"]["arguments"])
                
                tool_result = await self._execute_tool(func_name, func_args)
                
                expose_tool_visual = should_expose_tool_visual(
                    request.message,
                    func_args.get("layer_name") if isinstance(func_args, dict) else None,
                    func_name,
                )

                if isinstance(tool_result, dict):
                    if expose_tool_visual and tool_result.get("map_action"): map_actions.append(tool_result)
                    if expose_tool_visual and tool_result.get("map_actions"): map_actions.extend(tool_result["map_actions"])
                    if expose_tool_visual and tool_result.get("analytics_data"): analytics_data = tool_result.get("analytics_data")

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tcall["id"],
                    "content": json.dumps(tool_result),
                    "metadata": {"function": func_name}
                }
                messages.append(tool_msg)
                await self.history_service.save_message(
                    conv_id, "tool", tool_msg["content"], 
                    tool_call_id=tcall["id"], metadata=tool_msg["metadata"]
                )

        # Guardar la respuesta final (solo si no fue una respuesta vacía tras tools)
        suggestions = []
        if full_content:
            extracted_text, suggestions = extract_suggestions_from_text(full_content)
            await self.history_service.save_message(
                conv_id, "assistant", extracted_text,
                metadata={
                    "model": model_config.model_id, 
                    "map_actions": map_actions, 
                    "analytics_data": analytics_data,
                    "suggestions": suggestions
                }
            )

        latency_ms = int((time.time() - start_time) * 1000)
        cost = (total_tokens_in * (model_config.input_cost_per_1k or 0.0) / 1000) + \
               (total_tokens_out * (model_config.output_cost_per_1k or 0.0) / 1000)
        
        await self._save_audit_log(user.id, conv_id, model_config.name, total_tokens_in, total_tokens_out, cost, latency_ms)

        yield f"data: {json.dumps({'type': 'done', 'map_actions': map_actions, 'analytics_data': analytics_data, 'suggestions': suggestions, 'tokens_input': total_tokens_in, 'tokens_output': total_tokens_out, 'cost': cost})}\n\n"

    async def _execute_tool(self, name: str, args: dict) -> Any:
        try:
            if name == "consultar_predios": return await self.tools_service.consultar_predios(**args)
            elif name == "analizar_zona_extent": return await self.tools_service.analizar_zona_extent(**args)
            elif name == "consultar_estadisticas_capa": return await self.tools_service.consultar_estadisticas_capa(**args)
            elif name == "activate_layer": return await self.tools_service.activate_layer(**args)
            elif name == "activate_category": return await self.tools_service.activate_category(**args)
            elif name == "change_basemap": return await self.tools_service.change_basemap(**args)
            elif name == "zoom_to_location": return await self.tools_service.zoom_to_location(**args)
            elif name == "buscar_y_mostrar_entidad": return await self.tools_service.buscar_y_mostrar_entidad(**args)
            elif name == "buscar_y_mostrar_entidades": return await self.tools_service.buscar_y_mostrar_entidades(**args)
            elif name == "mostrar_ruta_animada": return await self.tools_service.mostrar_ruta_animada(**args)
            elif name == "listar_campos_capa": return await self.tools_service.listar_campos_capa(**args)
            elif name == "consultar_datos_tabla": return await self.tools_service.consultar_datos_tabla(**args)
            else: return f"Error: La herramienta {name} no existe."
        except Exception as e:
            return {"error": str(e)}

    async def _save_audit_log(self, user_id: UUID, conversation_id: UUID, model_name: str, tokens_in: int, tokens_out: int, cost: float, latency_ms: int):
        # Siempre insertamos un nuevo registro para cada turno de chat
        # para que el contador de límites de uso (mensajes por hora) sea preciso.
        stmt_insert = text("""
            INSERT INTO ia_audit_logs (user_id, conversation_id, model, tokens_input, tokens_output, cost, latency_ms, status)
            VALUES (:uid, :cid, :model, :tin, :tout, :cost, :lat, 'success')
        """)
        await self.db.execute(stmt_insert, {
            "uid": user_id, 
            "cid": conversation_id, 
            "model": model_name, 
            "tin": tokens_in, 
            "tout": tokens_out, 
            "cost": cost, 
            "lat": latency_ms
        })
        await self.db.commit()
