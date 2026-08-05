import asyncio
import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import app.db.base
from app.shared.db.session import get_db
from sqlalchemy import select
from app.Geo_Usuarios.model import User

async def check_users():
    async for db in get_db():
        result = await db.execute(select(User.email, User.full_name, User.role, User.is_active))
        users = result.all()
        print("\n================ USUARIOS EN BASE DE DATOS ================")
        if not users:
            print("No se encontraron usuarios en la tabla 'users'.")
        for user in users:
            print(f"Email: {user.email} | Nombre: {user.full_name} | Rol: {user.role} | Active: {user.is_active}")
        print("============================================================\n")
        break

if __name__ == "__main__":
    asyncio.run(check_users())
