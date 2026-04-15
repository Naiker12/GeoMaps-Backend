import logging
import json
import time
from uuid import UUID
from typing import List, Dict, Any, Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.infrastructure.ia_llm_client import LLMProviderFactory
from app.services.ia.prompt_builder import PromptBuilder
from app.services.ia.history_service import HistoryService
from app.services.ia.tools_service import ToolsService
from app.schemas.ia import ChatRequest, ChatResponse, Message, IAModelConfig
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
        return IAModelConfig(**row) if row else None

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
        return IAModelConfig(**row) if row else None

    async def _get_available_layers(self) -> List[Dict[str, Any]]:
        """Obtiene nombres y metadatos de campos de las capas disponibles."""
        try:
            # Seleccionar nombre y configuraciones de campos
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
                
                # Intentar sacar campos del config de la ficha
                if card and isinstance(card, dict) and "sections" in card:
                    for section in card["sections"]:
                        for field in section.get("fields", []):
                            fields.append(f"{field.get('key')} ({field.get('label')})")
                
                # O del config de estadísticas
                elif stats and isinstance(stats, dict) and "kpis" in stats:
                    for kpi in stats["kpis"]:
                        fields.append(f"{kpi.get('field')} ({kpi.get('label')})")
                
                # FALLBACK: Si no hay config, traer 1 ejemplo real de la base de datos
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
                            # Tomar hasta 8 llaves para dar contexto
                            fields = [f"{k}" for k in list(sample_row.keys())[:8]]
                    except Exception:
                        pass
                
                layers_metadata.append({
                    "name": name,
                    "fields": fields[:12] # Limitar para no saturar tokens
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
        
        # Verificar si la conversación existe si se proporcionó un ID
        if conv_id:
            check_exists = await self.db.execute(
                text("SELECT id FROM ia_conversations WHERE id = :cid AND user_id = :uid"),
                {"cid": conv_id, "uid": user.id}
            )
            if not check_exists.fetchone():
                conv_id = None # Forzar creación si no existe

        if not conv_id:
            conv_id = await self.history_service.create_conversation(
                user_id=user.id, 
                title=request.message[:50] + "...", 
                model_id=model_config.model_id
            )

        history = await self.history_service.get_trimmed_history(conv_id, user.id, max_messages=10)
        
        # Resumen de memoria de largo plazo
        conversation_summary = await self.history_service.get_conversation_summary(conv_id)
        if not conversation_summary and history and len(history) >= 15:
            try:
                summary_prompt = "Resume brevemente los datos y capas analizados en esta conversación para mantener contexto. Sé muy conciso."
                messages_for_summary = [{"role": msg.role, "content": msg.content} for msg in history[-15:] if msg.content and msg.role != "tool"]
                messages_for_summary.append({"role": "user", "content": summary_prompt})
                
                api_key_for_summary = settings.OPENROUTER_API_KEY
                summary_client = LLMProviderFactory.create(model_config.provider.lower(), api_key_for_summary, model_config.model_id)
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
                tokens_input=0,
                tokens_output=0,
                cost=0.0,
                latency_ms=0,
                tools_called=[],
                tools_called_raw=[],
                map_actions=[],
                analytics_data=None
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
        # Limitar historial a últimos 10 mensajes para ahorrar tokens
        for msg in (history if history else []):
            messages.append({
                "role": msg.role,
                "content": msg.content,
                "tool_calls": msg.metadata.get("tool_calls") if isinstance(msg.metadata, dict) else None,
                "tool_call_id": msg.tool_call_id
            })
        
        # Agregar el mensaje actual del usuario
        messages.append({"role": "user", "content": request.message})
        
        await self.history_service.save_message(conv_id, "user", request.message)

        api_key = settings.OPENROUTER_API_KEY
        client = LLMProviderFactory.create(model_config.provider.lower(), api_key, model_config.model_id)
        tools = await self.tools_service.get_tools_metadata() if model_config.has_function_calling else []
        
        total_tokens_in = 0
        total_tokens_out = 0
        final_response_content = ""
        map_actions = []
        tools_called = []
        analytics_data = None

        try:
            # Llamada Inicial
            response = await client.chat_complete(
                messages=[
                    Message(
                        role=m.get("role"),
                        content=m.get("content"),
                        tool_calls=m.get("tool_calls"),
                        tool_call_id=m.get("tool_call_id")
                    ) for m in messages
                ],
                tools=tools if tools else None,
            )
            
            if response.get("status") == "error":
                msg = response.get("error_message", "Unknown Error")
                if "429" in msg or "Demasiadas" in msg or "Límite" in msg:
                    raise LLMRateLimitException(msg)
                raise LLMException(msg)

            total_tokens_in += response.get("tokens_input", 0)
            total_tokens_out += response.get("tokens_output", 0)
            
            msg = response["message"]

            # Ciclo de Tool Calls (máximo 3 iteraciones para evitar bucles infinitos)
            iterations = 0
            while msg.get("tool_calls") and iterations < 3:
                iterations += 1
                messages.append(msg) # Agregar assistant message con tool calls
                
                # Guardar el mensaje del asistente que llamó a herramientas
                await self.history_service.save_message(
                    conv_id, "assistant", 
                    msg.get("content") or "", 
                    metadata={"tool_calls": msg.get("tool_calls")}
                )
                
                for tcall in msg["tool_calls"]:
                    func_name = tcall["function"]["name"]
                    func_args = json.loads(tcall["function"]["arguments"])
                    logger.info(f"IA llamando a herramienta: {func_name} con args {func_args}")
                    
                    # Ejecutar herramienta
                    tool_result = await self._execute_tool(func_name, func_args)
                    tools_called.append(func_name)
                    
                    # Capturar acciones de mapa y analytics
                    if isinstance(tool_result, dict):
                        # Acción única
                        if tool_result.get("map_action"):
                            map_actions.append(tool_result)
                        # Múltiples acciones
                        if tool_result.get("map_actions"):
                            for action in tool_result["map_actions"]:
                                # Estandarizar 'type' a 'map_action' si es necesario
                                if "type" in action and "map_action" not in action:
                                    action["map_action"] = action.pop("type")
                                map_actions.append(action)
                        
                        if tool_result.get("analytics_data"):
                            analytics_data = tool_result.get("analytics_data")

                    # Agregar resultado al historial envíado al LLM
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tcall["id"],
                        "name": func_name,
                        "content": json.dumps(tool_result)
                    })
                    
                    # Guardar respuesta de la herramienta en DB
                    await self.history_service.save_message(
                        conv_id, "tool", json.dumps(tool_result), 
                        tool_call_id=tcall["id"], metadata={"function": func_name}
                    )

                # Volver a llamar al LLM con los resultados
                response = await client.chat_complete(
                    messages=[
                        Message(
                            role=m.get("role"),
                            content=m.get("content"),
                            tool_calls=m.get("tool_calls"),
                            tool_call_id=m.get("tool_call_id")
                        ) for m in messages
                    ],
                    tools=tools if tools else None
                )
                if response.get("status") == "error":
                    msg = response.get("error_message", "Unknown Error")
                    if "429" in msg or "Demasiadas" in msg or "Límite" in msg:
                        raise LLMRateLimitException(msg)
                    raise LLMException(msg)

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
            
            await self._save_audit_log(
                user.id, conv_id, model_config.name, total_tokens_in, total_tokens_out, cost, latency_ms
            )

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

    async def _execute_tool(self, name: str, args: dict) -> Any:
        """Enrutador interno para ejecutar las herramientas de ToolsService."""
        try:
            if name == "consultar_predios":
                return await self.tools_service.consultar_predios(**args)
            elif name == "analizar_zona_extent":
                return await self.tools_service.analizar_zona_extent(**args)
            elif name == "consultar_estadisticas_capa":
                return await self.tools_service.consultar_estadisticas_capa(**args)
            elif name == "activate_layer":
                return await self.tools_service.activate_layer(**args)
            elif name == "zoom_to_location":
                return await self.tools_service.zoom_to_location(**args)
            elif name == "buscar_y_mostrar_entidad":
                return await self.tools_service.buscar_y_mostrar_entidad(**args)
            elif name == "mostrar_ruta_animada":
                return await self.tools_service.mostrar_ruta_animada(**args)
            elif name == "listar_campos_capa":
                return await self.tools_service.listar_campos_capa(**args)
            else:
                return f"Error: La herramienta {name} no existe."
        except Exception as e:
            return {"error": str(e)}

    async def _save_audit_log(self, user_id: UUID, conversation_id: UUID, model_name: str, tokens_in: int, tokens_out: int, cost: float, latency_ms: int):
        # 1. Buscar si ya existe una entrada para esta sesión (conversación + modelo)
        stmt_check = text("""
            SELECT id FROM ia_audit_logs 
            WHERE conversation_id = :cid AND model = :model 
            LIMIT 1
        """)
        res = await self.db.execute(stmt_check, {"cid": conversation_id, "model": model_name})
        row_id = res.scalar()

        if row_id:
            # 2. Actualizar acumulando valores
            stmt_update = text("""
                UPDATE ia_audit_logs 
                SET tokens_input = tokens_input + :tin,
                    tokens_output = tokens_output + :tout,
                    cost = cost + :cost,
                    latency_ms = (latency_ms + :lat) / 2
                WHERE id = :rid
            """)
            await self.db.execute(stmt_update, {
                "rid": row_id, 
                "tin": tokens_in, 
                "tout": tokens_out, 
                "cost": cost, 
                "lat": latency_ms
            })
        else:
            # 3. Crear nueva entrada
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
