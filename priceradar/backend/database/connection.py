from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "sqlite+aiosqlite:///./priceradar.db"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        from database import models_db  # noqa: F401 — garante que os modelos sejam registrados
        await conn.run_sync(Base.metadata.create_all)
        await _migrar_colunas(conn)


async def _migrar_colunas(conn):
    """Migração leve: adiciona colunas novas a tabelas já existentes (SQLite)."""
    result = await conn.execute(text("PRAGMA table_info(buscas)"))
    colunas = {row[1] for row in result.fetchall()}
    if "bairro" not in colunas:
        await conn.execute(text("ALTER TABLE buscas ADD COLUMN bairro VARCHAR"))
