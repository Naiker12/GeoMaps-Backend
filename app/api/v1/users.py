from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.db.session import get_db
from app.domain.models.user import User
from app.schemas.user_schema import UserBase, UserUpdate
from app.core.security.dependencies import get_current_user

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/", response_model=List[UserBase])
async def list_admin_users(
    db: AsyncSession = Depends(get_db)
):
    """
    Lista todos los usuarios para el panel administrativo.
    Accesible a través de /api/v1/admin/users
    """
    result = await db.execute(select(User))
    return result.scalars().all()

@router.get("/me", response_model=UserBase)
async def get_my_profile(
    current_user: User = Depends(get_current_user)
):
    """
    Retorna el perfil del usuario actual.
    """
    return current_user

@router.patch("/me", response_model=UserBase)
async def update_my_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Actualiza el perfil del usuario autenticado.
    """
    if user_update.full_name is not None:
        current_user.full_name = user_update.full_name
    
    if user_update.avatar_url is not None:
        current_user.avatar_url = user_update.avatar_url
        
    await db.commit()
    await db.refresh(current_user)
    return current_user

@router.patch("/{user_id}", response_model=UserBase)
async def update_user(
    user_id: UUID,
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Actualiza datos de un usuario por ID (rol, estado, etc).
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    if user_update.role is not None:
        if user_update.role not in ["USER", "ADMIN", "SUPER_ADMIN", "EDITOR"]:
            raise HTTPException(status_code=400, detail="Rol inválido")
        user.role = user_update.role
        
    if user_update.is_active is not None:
        user.is_active = user_update.is_active
        
    if user_update.full_name is not None:
        user.full_name = user_update.full_name

    if user_update.avatar_url is not None:
        user.avatar_url = user_update.avatar_url
        
    await db.commit()
    await db.refresh(user)
    return user

@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Elimina un usuario de la base de datos.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    await db.delete(user)
    await db.commit()
    return {"message": "Usuario eliminado correctamente"}
