from app.infrastructure.database.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    result = db.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"))
    print("--- TABLES ---")
    for row in result:
        print(row)
finally:
    db.close()
