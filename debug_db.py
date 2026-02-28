from app.infrastructure.database.session import SessionLocal
from app.domain.models.user import User
from app.domain.models.admin import Admin

db = SessionLocal()
try:
    print("--- USERS ---")
    users = db.query(User).all()
    for u in users:
        print(f"ID: {u.id} | Email: {u.email} | SupaID: {u.supabase_id} | Role: {u.role}")

    print("\n--- ADMINS ---")
    admins = db.query(Admin).all()
    for a in admins:
        print(f"ID: {a.id} | Email: {a.email} | Super: {a.is_superadmin}")
finally:
    db.close()
