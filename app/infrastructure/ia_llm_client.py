import abc
import logging
import json
import asyncio
import base64
from google import genai
from google.genai import types
from typing import List, Dict, Any, Optional, AsyncGenerator
from app.schemas.ia import Message

logger = logging.getLogger(__name__)

class LLMProvider(abc.ABC):
    """Clase base abstracta para proveedores de modelos de lenguaje (LLM)."""

    def __init__(self, api_key: str, model_id: str):
        self.api_key = api_key
        self.model_id = model_id

    @abc.abstractmethod
    async def chat_complete(
        self, 
        messages: List[Message], 
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Solicita una completación al proveedor."""
        pass

    @abc.abstractmethod
    async def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Solicita una completación vía streaming al proveedor."""
        pass

class GeminiProvider(LLMProvider):
    """Proveedor nativo de Google Gemini usando el SDK 'google-genai'."""

    def __init__(self, api_key: str, model_id: str):
        super().__init__(api_key, model_id)
        # Usamos v1beta para asegurar compatibilidad total con tools y modelos nuevos
        self.client = genai.Client(api_key=self.api_key, http_options={'api_version': 'v1beta'})

    def _convert_messages(self, messages: List[Message]) -> tuple[List[types.Content], Optional[str]]:
        """Convierte el formato de mensaje interno al formato de Gemini y extrae la instrucción de sistema."""
        import base64
        gemini_contents = []
        system_instruction = None
        
        for m in messages:
            if m.role == "system":
                system_instruction = m.content
                continue
                
            role = "user" if m.role in ["user", "tool"] else "model"
            parts = []
            
            # 1. Agregar texto
            if m.content:
                if m.role == "tool":
                    parts.append(types.Part.from_function_response(
                        name=m.metadata.get("function", "unknown"),
                        response={"result": m.content}
                    ))
                else:
                    parts.append(types.Part.from_text(text=m.content))
            
            # 2. Agregar Archivos Adjuntos (Visión)
            attachments = m.metadata.get("attachments") if m.metadata else None
            if attachments and isinstance(attachments, list):
                for att in attachments:
                    try:
                        mime_type = att.get("mime_type", "image/png")
                        base64_data = att.get("data", "")
                        if "," in base64_data:
                            base64_data = base64_data.split(",")[1]
                        
                        img_data = base64.b64decode(base64_data)
                        parts.append(types.Part.from_bytes(data=img_data, mime_type=mime_type))
                    except Exception as e:
                        logger.error(f"Error decodificando adjunto: {e}")
            
            # 3. Agregar Llamadas a Herramientas
            if m.metadata and "tool_calls" in m.metadata:
                for tcall in m.metadata["tool_calls"]:
                    parts.append(types.Part.from_function_call(
                        name=tcall["function"]["name"],
                        args=json.loads(tcall["function"]["arguments"])
                    ))
            
            if parts:
                gemini_contents.append(types.Content(
                    role=role,
                    parts=parts
                ))
        return gemini_contents, system_instruction

    def _convert_tools(self, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[types.Tool]]:
        """Convierte el formato de herramientas de OpenAI al formato types.Tool de Gemini."""
        if not tools:
            return None
        
        declarations = []
        for t in tools:
            if t.get("type") == "function":
                func = t["function"]
                # Convertimos el esquema de parámetros si es necesario
                # google-genai acepta el dict de OpenAI usualmente
                declarations.append(types.FunctionDeclaration(
                    name=func["name"],
                    description=func["description"],
                    parameters=func["parameters"]
                ))
        
        return [types.Tool(function_declarations=declarations)] if declarations else None

    async def chat_complete(
        self, 
        messages: List[Message], 
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        try:
            contents, system_instruction = self._convert_messages(messages)
            gemini_tools = self._convert_tools(tools)
            
            config = types.GenerateContentConfig(
                tools=gemini_tools,
                system_instruction=system_instruction,
                temperature=0.7,
            )

            response = None
            last_error = None

            for attempt in range(2):
                try:
                    # Usamos el cliente asíncrono nativo (aio)
                    response = await self.client.aio.models.generate_content(
                        model=self.model_id,
                        contents=contents,
                        config=config
                    )
                    break
                except Exception as e:
                    last_error = e
                    error_text = str(e).lower()
                    is_transient = (
                        "503" in error_text
                        or "unavailable" in error_text
                        or "overloaded" in error_text
                        or "busy" in error_text
                        or "high demand" in error_text
                        or "deadline" in error_text
                    )
                    if attempt == 0 and is_transient:
                        await asyncio.sleep(1.5)
                        continue
                    raise

            if response is None:
                raise last_error or RuntimeError("Gemini no retorno respuesta")
            
            # Extraer contenido y llamadas a funciones (tool calls)
            content = ""
            tool_calls = []
            
            if response.candidates:
                candidate = response.candidates[0]
                for part in candidate.content.parts:
                    if part.text:
                        content += part.text
                    if part.function_call:
                        tool_calls.append({
                            "id": f"call_{part.function_call.name}_{int(asyncio.get_event_loop().time())}",
                            "type": "function",
                            "function": {
                                "name": part.function_call.name,
                                "arguments": json.dumps(part.function_call.args)
                            }
                        })

            return {
                "status": "success",
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls if tool_calls else None
                },
                "tokens_input": response.usage_metadata.prompt_token_count if response.usage_metadata else 0,
                "tokens_output": response.usage_metadata.candidates_token_count if response.usage_metadata else 0,
                "latency_ms": 0
            }
        except Exception as e:
            error_str = str(e)
            logger.error(f"Gemini API Error (google-genai): {error_str}")
            status_code = 503
            error_code = "LLM_UNAVAILABLE"
            
            # Mensajes amigables para el usuario final según el tipo de error
            friendly_msg = "Lo siento, el servicio de IA no está disponible en este momento. Por favor, intenta de nuevo en unos minutos."
            if "404" in error_str or "not found" in error_str.lower():
                friendly_msg = "El modelo de IA no está disponible o no se encuentra configurado correctamente."
            elif "429" in error_str or "quota" in error_str.lower():
                status_code = 429
                error_code = "LLM_RATE_LIMIT"
                friendly_msg = "Has superado el límite de mensajes permitidos. Por favor, espera un momento antes de continuar."
            elif "503" in error_str or "overloaded" in error_str.lower() or "busy" in error_str.lower() or "deadline" in error_str.lower():
                error_code = "LLM_TEMPORARILY_UNAVAILABLE"
                friendly_msg = "El servicio de IA está recibiendo muchas peticiones en este momento y no podemos atenderte. Por favor, intenta de nuevo en unos segundos."
            
            return {
                "status": "error",
                "error_message": friendly_msg,
                "status_code": status_code,
                "error_code": error_code,
                "technical_details": error_str
            }

    async def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            contents, system_instruction = self._convert_messages(messages)
            gemini_tools = self._convert_tools(tools)
            
            config = types.GenerateContentConfig(
                tools=gemini_tools,
                system_instruction=system_instruction,
                temperature=0.7,
            )
            
            # Usamos el stream asíncrono nativo (aio)
            async for chunk in self.client.aio.models.generate_content_stream(
                model=self.model_id,
                contents=contents,
                config=config
            ):
                if chunk.candidates:
                    candidate = chunk.candidates[0]
                    for part in candidate.content.parts:
                        if part.text:
                            yield {"type": "text", "content": part.text}
                        if part.function_call:
                            yield {
                                "type": "tool_call",
                                "tool_calls": [{
                                    "id": f"call_{part.function_call.name}_{int(asyncio.get_event_loop().time())}",
                                    "function": {
                                        "name": part.function_call.name,
                                        "arguments": json.dumps(part.function_call.args)
                                    }
                                }]
                            }
                
                if chunk.usage_metadata:
                    yield {
                        "type": "done",
                        "tokens_input": chunk.usage_metadata.prompt_token_count,
                        "tokens_output": chunk.usage_metadata.candidates_token_count
                    }
                    
        except Exception as e:
            error_str = str(e)
            logger.error(f"Gemini Stream Error (google-genai): {error_str}")
            
            friendly_msg = "Error en la conexión con la IA. Por favor, intenta de nuevo."
            if "NOT_FOUND" in error_str or "404" in error_str:
                friendly_msg = f"Modelo no encontrado ({self.model_id})."
            elif "429" in error_str:
                friendly_msg = "Límite de API de Google excedido."
                
            yield {"type": "error", "content": friendly_msg}

class LLMProviderFactory:
    """Fábrica de proveedores LLM. Actualmente usa exclusivamente Gemini vía 'google-genai'."""
    
    @staticmethod
    def create(provider: str, api_key: str, model_id: str) -> LLMProvider:
        from app.core.config import settings
        key = api_key or settings.GOOGLE_API
        # Forzamos GeminiProvider para todos los casos si queremos migración total
        return GeminiProvider(key, model_id)
