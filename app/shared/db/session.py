"""Configuración de la sesión de base de datos async con SQLAlchemy."""

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.shared.core.config import settings

_db_url = str(settings.DATABASE_URL)
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+psycopg://", 1)
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)

_url = make_url(_db_url)
_is_supabase_transaction_pooler = (
    (_url.host or "").endswith(".pooler.supabase.com") and _url.port == 6543
)

_engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
}

if _is_supabase_transaction_pooler:
    _engine_kwargs["poolclass"] = NullPool
    _engine_kwargs["connect_args"] = {"prepare_threshold": None}
else:
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20

engine = create_async_engine(_db_url, **_engine_kwargs)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Clase base para todos los modelos ORM."""


async def get_db():
    """Dependency que provee una sesión de base de datos."""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
