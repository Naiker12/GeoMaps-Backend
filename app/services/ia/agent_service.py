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

    async def _get_available_layers(self) -> List[str]:
        """Obtiene todos los nombres de las capas disponibles en el proyecto."""
        try:
            query = text("SELECT name FROM public.layers WHERE visibility != 'PRIVATE'")
            result = await self.db.execute(query)
            rows = result.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Error cargando capas disponibles: {e}")
            return []

    async def chat(self, request: ChatRequest, user: Any) -> ChatResponse:
        start_time = time.time()
        
        model_config = await self._get_model_config(request.model)
        if not model_config:
            model_config = await self._get_any_active_model()
            if not model_config:
                raise ValueError("No hay modelos de IA activos disponibles en el sistema.")

        conv_id = request.conversation_id
        if not conv_id:
            conv_id = await self.history_service.create_conversation(
                user_id=user.id, 
                title=request.message[:50] + "...", 
                model_id=model_config.model_id
            )

        history = await self.history_service.get_messages(conv_id, user.id)
        if history is None:
            # Si no hay historial o la conversa no es del usuario, crear una
            # (En el flujo real frontend suele crearla primero, pero manejamos fallback)
            pass

        # 2.5 Obtener capas disponibles para informar al modelo
        available_layers = await self._get_available_layers()

        # 3. Construir Prompts
        system_prompt = self.prompt_builder.build_system_prompt(
            bbox=request.context_mapa.get("extent") if request.context_mapa else None,
            active_layers=request.context_mapa.get("active_layers") if request.context_mapa else None,
            available_layers=available_layers,
            user_name=user.full_name or user.email
        )

        messages = [{"role": "system", "content": system_prompt}]
        # Limitar historial a últimos 10 mensajes para ahorrar tokens
        for msg in (history[-10:] if history else []):
            messages.append({
                "role": msg.role,
                "content": msg.content,
                "tool_calls": msg.metadata.get("tool_calls") if isinstance(msg.metadata, dict) else None,
                "tool_call_id": msg.tool_call_id
            })
        
        # Agregar el mensaje actual del usuario
        messages.append({"role": "user", "content": request.message})
        
        # 4. Guardar Mensaje del Usuario
        await self.history_service.save_message(conv_id, "user", request.message)

        # 5. Ejecutar Ciclo LLM con Function Calling
        api_key = settings.OPENROUTER_API_KEY
        client = LLMProviderFactory.create(model_config.provider.lower(), api_key, model_config.model_id)
        tools = await self.tools_service.get_tools_metadata() if model_config.has_function_calling else []
        
        total_tokens_in = 0
        total_tokens_out = 0
        final_response_content = ""
        map_actions = []
        tools_called = []

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
                raise Exception(response.get("error_message"))

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
                    
                    # Si es una acción del mapa, la guardamos para el frontend
                    if isinstance(tool_result, dict) and tool_result.get("map_action"):
                        map_actions.append(tool_result)

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
                    raise Exception(response.get("error_message"))

                total_tokens_in += response.get("tokens_input", 0)
                total_tokens_out += response.get("tokens_output", 0)
                msg = response["message"]

            final_response_content = msg.get("content") or ""
            
            # 6. Guardar Respuesta Final
            await self.history_service.save_message(
                conv_id, "assistant", final_response_content,
                metadata={"model": model_config.model_id, "map_actions": map_actions}
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
                map_actions=map_actions
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
            elif name == "activate_layer":
                return await self.tools_service.activate_layer(**args)
            elif name == "zoom_to_location":
                return await self.tools_service.zoom_to_location(**args)
            else:
                return f"Error: La herramienta {name} no existe."
        except Exception as e:
            return {"error": str(e)}

    async def _save_audit_log(self, user_id: UUID, conversation_id: UUID, model_name: str, tokens_in: int, tokens_out: int, cost: float, latency_ms: int):
        stmt = text("""
            INSERT INTO ia_audit_logs (user_id, conversation_id, model, tokens_input, tokens_output, cost, latency_ms, status)
            VALUES (:uid, :cid, :model, :tin, :tout, :cost, :lat, 'success')
        """)
        await self.db.execute(stmt, {
            "uid": user_id, 
            "cid": conversation_id, 
            "model": model_name, 
            "tin": tokens_in, 
            "tout": tokens_out, 
            "cost": cost, 
            "lat": latency_ms
        })
        await self.db.commit()
