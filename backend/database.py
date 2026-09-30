"""Database setup for RK Legal Bot.

Async SQLAlchemy engine with PostgreSQL/SQLite compatibility:
- Default: sqlite+aiosqlite:///./chat.db
- Production: set DATABASE_URL=postgresql+asyncpg://user:pass@host/db
"""

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_DEFAULT_DB_PATH = Path(__file__).parent / "chat.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH}")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    # SQLite needs check_same_thread=False in async mode; harmless for PostgreSQL.
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Create tables on startup. For production PostgreSQL, prefer Alembic migrations."""
    from models import ChatMessage, ChatSession  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """FastAPI dependency yielding an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
