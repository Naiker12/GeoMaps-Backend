from pydantic import BaseModel, EmailStr
from typing import Optional, Any

class UserBase(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    role: str
    avatar_url: Optional[str] = None

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
