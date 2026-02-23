from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

class UserBase(BaseModel):
    email: str
    full_name: Optional[str] = None
    role: str = "USER" # USER, ADMIN, SUPER_ADMIN

class UserCreate(UserBase):
    id: UUID # El UUID que viene de Supabase Auth

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class UserResponse(UserBase):
    id: UUID
    auth_provider: Optional[str] = None
    is_admin_panel: bool
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True
