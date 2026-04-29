import logging
import json
import time
import asyncio
from uuid import UUID
from typing import List, Dict, Any, Optional, AsyncGenerator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.infrastructure.ia_llm_client import LLMProviderFactory
from app.services.ia.prompt_builder import PromptBuilder
from app.services.ia.history_service import HistoryService
from app.services.ia.tools import ToolsService
from app.schemas.ia import ChatRequest, ChatResponse, Message, IAModelConfig, StreamChunk
from app.core.exceptions import LLMException, LLMRateLimitException

GRAFICO_KEYWORDS = ["gráfico", "grafica", "chart", "visualiza", "barras", "pastel", "pie", "línea", "muéstrame en gráfico"]

def needs_chart_clarification(message: str) -> bool:
    """Retorna True si el usuario quiere un gráfico pero no especificó el tipo."""
    msg_lower = message.lower()
    has_chart_intent = any(kw in msg_lower for kw in GRAFICO_KEYWORDS)
    chart_prefs_complete = "barras" in msg_lower or "pastel" in msg_lower or "línea" in msg_lower or "pie" in msg_lower
    return has_chart_intent and not chart_prefs_complete

logger = logging.getLogger(__name__)

class AgentService:
    def __init__(self, db: AsyncSession, model_config: IAModelConfig = None):
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
        # Cast decimal to float for Pydantic
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
                logger.warning(f"No se pudo generar el resumen automátio: {e}")

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
        system_prompt = self.prompt_builder.build_system_prompt(
            bbox=request.context_mapa.get("extent") if request.context_mapa else None,
            active_layers=[l["name"] for l in request.context_mapa.get("layers", [])] if request.context_mapa and request.context_mapa.get("layers") else None,
            available_layers=available_layers,
            user_name=user.full_name or user.email,
            conversation_summary=conversation_summary
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
        messages.append({"role": "user", "content": request.message})
        
        await self.history_service.save_message(conv_id, "user", request.message)

        client = LLMProviderFactory.create(model_config.provider.lower(), settings.GOOGLE_API, model_config.model_id)
        tools = await self.tools_service.get_tools_metadata() if model_config.has_function_calling else []
        
        total_tokens_in = 0
        total_tokens_out = 0
        map_actions = []
        tools_called = []
        analytics_data = None

        try:
            response = await client.chat_complete(
                messages=[Message(**m) for m in messages],
                tools=tools if tools else None,
            )
            
            if response.get("status") == "error":
                raise LLMException(response.get("error_message", "Unknown Error"))

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
                    
                    if isinstance(tool_result, dict):
                        if tool_result.get("map_action"): map_actions.append(tool_result)
                        if tool_result.get("map_actions"):
                            for action in tool_result["map_actions"]:
                                if "type" in action and "map_action" not in action:
                                    action["map_action"] = action.pop("type")
                                map_actions.append(action)
                        if tool_result.get("analytics_data"): analytics_data = tool_result.get("analytics_data")

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
                    raise LLMException(response.get("error_message", "Unknown Error"))

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
            cost = (total_tokens_in * model_config.input_cost_per_1k / 1000) + \
                   (total_tokens_out * model_config.output_cost_per_1k / 1000)
            
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
                tools_called_raw=msg.get("tool_calls") or [],
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
        system_prompt = self.prompt_builder.build_system_prompt(
            bbox=request.context_mapa.get("extent") if request.context_mapa else None,
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
        messages.append({"role": "user", "content": request.message})
        
        await self.history_service.save_message(conv_id, "user", request.message)

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
            # 1. Guardar el mensaje del asistente con los tool_calls
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

            # 2. Ejecutar herramientas y agregar respuestas
            for tcall in current_tool_calls:
                func_name = tcall["function"]["name"]
                func_args = json.loads(tcall["function"]["arguments"])
                
                tool_result = await self._execute_tool(func_name, func_args)
                
                if isinstance(tool_result, dict):
                    if tool_result.get("map_action"): map_actions.append(tool_result)
                    if tool_result.get("map_actions"): map_actions.extend(tool_result["map_actions"])
                    if tool_result.get("analytics_data"): analytics_data = tool_result.get("analytics_data")

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
        if full_content:
            await self.history_service.save_message(
                conv_id, "assistant", full_content,
                metadata={"model": model_config.model_id, "map_actions": map_actions, "analytics_data": analytics_data}
            )

        latency_ms = int((time.time() - start_time) * 1000)
        cost = (total_tokens_in * model_config.input_cost_per_1k / 1000) + \
               (total_tokens_out * model_config.output_cost_per_1k / 1000)
        
        await self._save_audit_log(user.id, conv_id, model_config.name, total_tokens_in, total_tokens_out, cost, latency_ms)

        yield f"data: {json.dumps({'type': 'done', 'map_actions': map_actions, 'analytics_data': analytics_data, 'tokens_input': total_tokens_in, 'tokens_output': total_tokens_out, 'cost': cost})}\n\n"

    async def _execute_tool(self, name: str, args: dict) -> Any:
        try:
            if name == "consultar_predios": return await self.tools_service.consultar_predios(**args)
            elif name == "analizar_zona_extent": return await self.tools_service.analizar_zona_extent(**args)
            elif name == "consultar_estadisticas_capa": return await self.tools_service.consultar_estadisticas_capa(**args)
            elif name == "activate_layer": return await self.tools_service.activate_layer(**args)
            elif name == "zoom_to_location": return await self.tools_service.zoom_to_location(**args)
            elif name == "buscar_y_mostrar_entidad": return await self.tools_service.buscar_y_mostrar_entidad(**args)
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
