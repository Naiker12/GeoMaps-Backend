import sys
import os
from sqlalchemy.orm import Session
from app.infrastructure.database.session import SessionLocal
from app.domain.models.admin import Admin
from app.core.security.password import hash_password

def seed_super_admin():
    db: Session = SessionLocal()
    try:
        # Verificar si ya existe el superadmin
        admin_email = "admin@geomaps.com"
        existing_admin = db.query(Admin).filter(Admin.email == admin_email).first()
        
        if existing_admin:
            print(f"Updating password for existing admin: {admin_email}")
            existing_admin.password_hash = hash_password("Geomaps2024!")
            db.commit()
            print("Password updated.")
            return

        print(f"Creating super admin: {admin_email}")
        new_admin = Admin(
            email=admin_email,
            password_hash=hash_password("Geomaps2024!"),
            is_superadmin=True,
            is_active=True
        )
        db.add(new_admin)
        db.commit()
        print("Super admin created successfully.")
    except Exception as e:
        print(f"Error seeding super admin: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Asegurarnos de que el path esté correcto
    sys.path.append(os.getcwd())
    seed_super_admin()
