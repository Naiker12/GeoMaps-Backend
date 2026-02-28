from app.infrastructure.database.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    result = db.execute(text("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = 'users'"))
    print("--- USERS COLUMNS ---")
    for row in result:
        print(row)
finally:
    db.close()
