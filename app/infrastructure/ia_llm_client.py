import abc
import time
import httpx
from typing import List, Dict, Any, Optional
from app.schemas.ia import Message

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

class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-compatible provider (targeting OpenRouter)."""

    def __init__(self, api_key: str, model_id: str, base_url: str):
        super().__init__(api_key, model_id)
        self.base_url = base_url

    async def chat_complete(
        self, 
        messages: List[Message], 
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        
        start_time = time.time()
        
        formatted_messages = []
        for m in messages:
            msg_dict = {"role": m.role, "content": m.content or ""}
            if m.tool_calls: msg_dict["tool_calls"] = m.tool_calls
            if m.tool_call_id: msg_dict["tool_call_id"] = m.tool_call_id
            formatted_messages.append(msg_dict)

        payload = {
            "model": self.model_id,
            "messages": formatted_messages,
        }
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://geomaps.app",
            "X-Title": "GeoMaps IA"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=90.0
                )
                
                if response.status_code != 200:
                    error_body = response.text
                    return {
                        "status": "error",
                        "error_message": f"OpenRouter API Error {response.status_code}: {error_body}",
                        "latency_ms": int((time.time() - start_time) * 1000)
                    }

                data = response.json()
                choice = data["choices"][0]
                return {
                    "message": choice["message"],
                    "tokens_input": data.get("usage", {}).get("prompt_tokens", 0),
                    "tokens_output": data.get("usage", {}).get("completion_tokens", 0),
                    "latency_ms": int((time.time() - start_time) * 1000),
                    "status": "success"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error_message": f"Transport Error: {str(e)}",
                    "latency_ms": int((time.time() - start_time) * 1000)
                }

class LLMProviderFactory:
    """Factory aimed exclusively at OpenRouter for multi-model simplicity."""
    
    @staticmethod
    def create(provider: str, api_key: str, model_id: str) -> LLMProvider:
        # Forzar OpenRouter como hub central de modelos
        return OpenAICompatibleProvider(
            api_key, 
            model_id, 
            "https://openrouter.ai/api/v1"
        )
