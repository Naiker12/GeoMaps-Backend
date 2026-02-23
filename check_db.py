from app.infrastructure.database.session import SessionLocal
from app.domain.models.admin import Admin

def check_admins():
    db = SessionLocal()
    try:
        admins = db.query(Admin).all()
        print(f"Total admins: {len(admins)}")
        for a in admins:
            print(f"- Email: {a.email}, Active: {a.is_active}, Hash: {a.password_hash[:10]}...")
    finally:
        db.close()

if __name__ == "__main__":
    check_admins()
