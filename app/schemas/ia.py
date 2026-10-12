from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, UUID4


class Message(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    model: str = "gemini-2.0-flash"
    conversation_id: Optional[UUID4] = None
    context_mapa: Optional[Dict[str, Any]] = Field(default_factory=dict)
    geo_context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    historial: Optional[List[Message]] = Field(default_factory=list)


class DeleteConversationsRequest(BaseModel):
    conversation_ids: List[UUID4] = Field(default_factory=list)


class ChatResponse(BaseModel):
    message: str
    conversation_id: UUID4
    model_used: str
    tokens_input: Optional[int] = 0
    tokens_output: Optional[int] = 0
    cost: Optional[float] = 0.0
    latency_ms: Optional[int] = 0
    tools_called: List[Any] = Field(default_factory=list)
    tools_called_raw: List[Any] = Field(default_factory=list)
    map_actions: List[Dict[str, Any]] = Field(default_factory=list)
    analytics_data: Optional[Dict[str, Any]] = None
    analysis_results: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    pdf_export: bool = False


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
    metadata: Dict[str, Any] = Field(default_factory=dict)
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
