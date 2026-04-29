import abc
import logging
import json
import asyncio
from google import genai
from google.genai import types
from typing import List, Dict, Any, Optional, AsyncGenerator
from app.schemas.ia import Message

logger = logging.getLogger(__name__)

class LLMProvider(abc.ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, api_key: str, model_id: str):
        self.api_key = api_key
        self.model_id = model_id

    @abc.abstractmethod
    async def chat_complete(
        self, 
        messages: List[Message], 
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Request completion from the provider."""
        pass

    @abc.abstractmethod
    async def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Request streaming completion from the provider."""
        pass

class GeminiProvider(LLMProvider):
    """Native Google Gemini provider using the new google-genai SDK."""

    def __init__(self, api_key: str, model_id: str):
        super().__init__(api_key, model_id)
        # Usamos v1beta para asegurar compatibilidad total con tools y modelos nuevos
        self.client = genai.Client(api_key=self.api_key, http_options={'api_version': 'v1beta'})

    def _convert_messages(self, messages: List[Message]) -> tuple[List[types.Content], Optional[str]]:
        """Converts internal Message format to Gemini format and extracts system instruction."""
        gemini_contents = []
        system_instruction = None
        
        for m in messages:
            if m.role == "system":
                system_instruction = m.content
                continue
                
            # El rol para respuestas de herramientas en Gemini v1beta es 'user' 
            # pero el contenido debe tener partes de function_response
            role = "user" if m.role in ["user", "tool"] else "model"
            
            parts = []
            if m.content:
                if m.role == "tool":
                    parts.append(types.Part.from_function_response(
                        name=m.metadata.get("function", "unknown"),
                        response={"result": m.content}
                    ))
                else:
                    parts.append(types.Part.from_text(text=m.content))
            
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
        """Converts OpenAI tool format to Gemini types.Tool format."""
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

            # Ejecución en un hilo para no bloquear el loop si el SDK no es full async
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: self.client.models.generate_content(
                    model=self.model_id,
                    contents=contents,
                    config=config
                )
            )
            
            # Extraer contenido y tool calls
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
            
            # Mensajes amigables según el tipo de error
            friendly_msg = "Lo siento, el servicio de IA no está disponible en este momento. Por favor, intenta de nuevo en unos minutos."
            if "404" in error_str or "not found" in error_str.lower():
                friendly_msg = "El modelo de IA no está disponible o no se encuentra configurado correctamente."
            elif "429" in error_str or "quota" in error_str.lower():
                friendly_msg = "Has superado el límite de mensajes permitidos. Por favor, espera un momento antes de continuar."
            elif "503" in error_str or "overloaded" in error_str.lower() or "busy" in error_str.lower() or "deadline" in error_str.lower():
                friendly_msg = "El servicio de IA está recibiendo muchas peticiones en este momento y no podemos atenderte. Por favor, intenta de nuevo en unos segundos."
            
            return {
                "status": "error",
                "error_message": friendly_msg,
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
            
            # El streaming en el nuevo SDK
            response_stream = self.client.models.generate_content_stream(
                model=self.model_id,
                contents=contents,
                config=config
            )
            
            for chunk in response_stream:
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
    """Factory for LLM providers. Now exclusively Gemini with google-genai."""
    
    @staticmethod
    def create(provider: str, api_key: str, model_id: str) -> LLMProvider:
        from app.core.config import settings
        key = api_key or settings.GOOGLE_API
        # Forzamos GeminiProvider para todos los casos si queremos migración total
        return GeminiProvider(key, model_id)
