from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, UUID4

class Message(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}

class ChatRequest(BaseModel):
    message: str
    model: str = "gemini-2.0-flash"
    conversation_id: Optional[UUID4] = None
    context_mapa: Optional[Dict[str, Any]] = None
    historial: Optional[List[Message]] = []

class DeleteConversationsRequest(BaseModel):
    conversation_ids: List[UUID4] = Field(default_factory=list)

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str

class ChatResponse(BaseModel):
    message: str
    conversation_id: UUID4
    model_used: str
    tokens_input: Optional[int] = 0
    tokens_output: Optional[int] = 0
    cost: Optional[float] = 0.0
    latency_ms: Optional[int] = 0
    tools_called: List[Any] = []
    tools_called_raw: List[Any] = []
    map_actions: List[Dict[str, Any]] = []
    analytics_data: Optional[Dict[str, Any]] = None

class StreamChunk(BaseModel):
    """Chunk individual enviado vía SSE."""
    type: str  # "text" | "tool_status" | "done" | "error"
    content: Optional[str] = None
    tool_name: Optional[str] = None
    map_actions: Optional[List[Dict[str, Any]]] = None
    analytics_data: Optional[Dict[str, Any]] = None
    conversation_id: Optional[UUID4] = None
    model_used: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost: float = 0.0

class IAModelConfig(BaseModel):
    id: Optional[UUID4] = None
    name: str
    provider: str
    model_id: str
    is_active: bool = True
    input_cost_per_1k: Optional[float] = 0.0
    output_cost_per_1k: Optional[float] = 0.0
    has_function_calling: Optional[bool] = True
    has_vision: Optional[bool] = False
    max_context_tokens: Optional[int] = 4096

    class Config:
        from_attributes = True

class Conversation(BaseModel):
    id: UUID4
    title: str
    model_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class MessageRead(BaseModel):
    id: UUID4
    role: str
    content: Optional[str] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime

    class Config:
        from_attributes = True

class IASuggestion(BaseModel):
    id: UUID4
    text: str
    category: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool = True

class IAUsageResponse(BaseModel):
    current: int
    limit: int
    is_blocked: bool
    remaining_seconds: int
    next_reset: Optional[datetime] = None
