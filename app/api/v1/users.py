from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.infrastructure.database.session import get_db
from app.domain.models.user import User
from app.schemas.user_schema import UserBase, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/", response_model=List[UserBase])
async def list_admin_users(
    db: Session = Depends(get_db)
):
    """
    Lista todos los usuarios para el panel administrativo.
    Accesible a través de /api/v1/admin/users
    """
    return db.query(User).all()

@router.patch("/{user_id}", response_model=UserBase)
async def update_user(
    user_id: UUID,
    user_update: UserUpdate,
    db: Session = Depends(get_db)
):
    """
    Actualiza datos de un usuario (rol, estado, etc).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    if user_update.role is not None:
        if user_update.role not in ["user", "admin", "super_admin"]:
            raise HTTPException(status_code=400, detail="Rol inválido")
        user.role = user_update.role
        
    if user_update.is_active is not None:
        user.is_active = user_update.is_active
        
    if user_update.full_name is not None:
        user.full_name = user_update.full_name
        
    db.commit()
    db.refresh(user)
    return user

@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Elimina un usuario de la tabla pública.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    db.delete(user)
    db.commit()
    return {"message": "Usuario eliminado de la base de datos pública"}
