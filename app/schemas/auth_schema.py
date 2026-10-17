from pydantic import BaseModel, EmailStr
from typing import Optional, Any, List
from datetime import datetime
from uuid import UUID

class UserBase(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    role: str
    avatar_url: Optional[str] = None
    job_title: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True
    last_login: Optional[datetime] = None

class AuthResponse(BaseModel):
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user: Optional[UserBase] = None
    message: Optional[str] = None

class MagicLinkRequest(BaseModel):
    email: EmailStr

class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str

class SessionResponse(BaseModel):
    id: UUID
    device: str
    location: str
    last_active: datetime
    is_current: bool

    class Config:
        from_attributes = True
