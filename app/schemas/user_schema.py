from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    role: str
    is_active: bool = True
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    role: str
    password: str

class UserResponse(UserBase):
    class Config:
        from_attributes = True
