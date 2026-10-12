from pydantic import BaseModel, ConfigDict, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.db.models.user import UserRole

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

class UserProfileUpdate(BaseModel):
    """Campos que el usuario puede cambiar en su propio perfil."""

    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    job_title: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None

class UserUpdate(UserProfileUpdate):
    """Actualización administrativa, incluyendo rol y estado."""

    model_config = ConfigDict(extra="ignore")

    is_active: Optional[bool] = None
    role: Optional[UserRole] = None

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: Optional[UserRole] = UserRole.USER
    is_active: Optional[bool] = True
