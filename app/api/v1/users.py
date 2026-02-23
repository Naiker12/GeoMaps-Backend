from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.infrastructure.database.session import get_db
from app.core.security.dependencies import get_current_admin
from app.domain.models.user import User
from app.core.security.password import hash_password
from app.domain.models.admin import Admin
from app.schemas.user_schema import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/", response_model=List[UserResponse])
async def list_users(
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    """
    Lista todos los usuarios (Admins y Usuarios finales).
    """
    # Obtenemos Admins
    admins = db.query(Admin).all()
    admin_list = [
        {
            "id": str(a.id),
            "email": a.email,
            "full_name": "Administrador",
            "role": "SUPER_ADMIN" if a.is_superadmin else "ADMIN",
            "is_active": a.is_active,
            "last_login": None,
            "created_at": a.created_at
        }
        for a in admins
    ]
    
    # Obtenemos Usuarios
    users = db.query(User).all()
    user_list = [
        {
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
            "last_login": u.last_login,
            "created_at": u.created_at
        }
        for u in users
    ]
    
    return admin_list + user_list

@router.post("/", response_model=dict)
async def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    """
    Crea un nuevo usuario o administrador.
    """
    # Verificar si ya existe
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    existing_admin = db.query(Admin).filter(Admin.email == user_data.email).first()
    
    if existing_user or existing_admin:
        raise HTTPException(status_code=400, detail="El correo electrónico ya está registrado")
    
    password_hash = hash_password(user_data.password)
    
    if user_data.role in ["super_admin", "admin"]:
        new_admin = Admin(
            email=user_data.email,
            password_hash=password_hash,
            is_superadmin=(user_data.role == "super_admin")
        )
        db.add(new_admin)
    else:
        new_user = User(
            email=user_data.email,
            full_name=user_data.name,
            password_hash=password_hash,
            role=user_data.role.upper(),
            provider="local"
        )
        db.add(new_user)
        
    db.commit()
    return {"message": f"Usuario {user_data.email} creado correctamente"}

@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    """
    Elimina un usuario o administrador por su ID.
    """
    # Intentar en Admins
    admin_to_del = db.query(Admin).filter(Admin.id == user_id).first()
    if admin_to_del:
        if admin_to_del.id == admin.id:
            raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")
        db.delete(admin_to_del)
        db.commit()
        return {"message": "Administrador eliminado"}
        
    # Intentar en Usuarios
    user_to_del = db.query(User).filter(User.id == user_id).first()
    if user_to_del:
        db.delete(user_to_del)
        db.commit()
        return {"message": "Usuario eliminado"}
        
    raise HTTPException(status_code=404, detail="Usuario no encontrado")

@router.patch("/{user_id}/role")
async def update_user_role(
    user_id: str,
    role: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    """
    Actualiza el rol de un usuario. Solo accesible por administradores.
    Roles permitidos: USER, ADMIN, SUPER_ADMIN
    """
    if role not in ["USER", "ADMIN", "SUPER_ADMIN"]:
        raise HTTPException(status_code=400, detail="Rol inválido")
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    user.role = role
    db.commit()
    return {"message": f"Rol de {user.email} actualizado a {role}"}
