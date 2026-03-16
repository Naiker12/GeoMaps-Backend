from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID

class UserBase(BaseModel):
    id: UUID
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    job_title: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    job_title: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None
