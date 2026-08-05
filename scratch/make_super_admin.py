import asyncio
import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import app.db.base
from app.shared.db.session import get_db
from sqlalchemy import update
from app.Geo_Usuarios.model import User, UserRole

async def make_super_admin():
    target_email = "naikergomez0123@gmail.com"
    async for db in get_db():
        stmt = (
            update(User)
            .where(User.email == target_email)
            .values(role=UserRole.SUPER_ADMIN)
        )
        await db.execute(stmt)
        await db.commit()
        print(f"Usuario {target_email} actualizado exitosamente a SUPER_ADMIN en Supabase PostgreSQL.")
        break

if __name__ == "__main__":
    asyncio.run(make_super_admin())
