from app.infrastructure.database.session import SessionLocal
from sqlalchemy import text
import sys

db = SessionLocal()
try:
    print("Iniciando migración manual...")
    # Agregar columnas una por una
    commands = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS supabase_id UUID UNIQUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'user'",
        "ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_users_supabase_id ON users (supabase_id)",
        "UPDATE users SET role = 'ADMIN' WHERE email = 'admin@geomaps.com' AND role != 'ADMIN'"
    ]
    
    for cmd in commands:
        print(f"Ejecutando: {cmd}")
        db.execute(text(cmd))
    
    db.commit()
    print("Migración completada.")
except Exception as e:
    db.rollback()
    print(f"ERROR: {e}")
    sys.exit(1)
finally:
    db.close()
