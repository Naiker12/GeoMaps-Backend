import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, EmailStr, Field


class SupportRequestCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    email: EmailStr
    type: str = Field(..., min_length=2, max_length=50)
    message: str = Field(..., min_length=8, max_length=5000)
    source: str = Field(default="help_panel", max_length=50)
    metadata_: Dict[str, Any] = Field(default_factory=dict)


class SupportRequestUpdate(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(new|reviewing|resolved)$")
    priority: Optional[str] = Field(default=None, pattern="^(low|normal|high|urgent)$")
    notes: Optional[str] = None
    assigned_to: Optional[uuid.UUID] = None


class SupportReplyCreate(BaseModel):
    response_message: str = Field(..., min_length=8, max_length=5000)
    mark_resolved: bool = True


class SupportRequestResponse(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    assigned_to: Optional[uuid.UUID] = None
    name: str
    email: EmailStr
    type: str
    message: str
    status: str
    priority: str
    notes: Optional[str] = None
    response_message: Optional[str] = None
    source: str
    metadata_: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    email_sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        populate_by_name = True


class SupportRequestListResponse(BaseModel):
    items: list[SupportRequestResponse]
    total: int
    page: int
    limit: int
