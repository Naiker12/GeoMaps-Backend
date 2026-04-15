import asyncio
import selectors
import sys
from app.db.session import engine
from sqlalchemy import text

async def main():
    print("Iniciando habilitación de extensión unaccent...")
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS unaccent;'))
    print("Extensión unaccent habilitada con éxito.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
