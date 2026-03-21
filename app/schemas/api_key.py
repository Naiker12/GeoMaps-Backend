import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.db.models.api_key import APIKeyStatus

class APIKeyBase(BaseModel):
    name: str = "Primary Key"

class APIKeyCreate(APIKeyBase):
    pass

class APIKeyUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[APIKeyStatus] = None

class APIKeyResponse(APIKeyBase):
    id: uuid.UUID
    key_prefix: str
    hint: str
    created_at: datetime
    last_used: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    status: APIKeyStatus
    
    # We include the full key only once during creation
    key: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
