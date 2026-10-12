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
    # Validate pooled connections on checkout: a client disconnect cancels the
    # aiosqlite terminate cleanup, leaving a dead connection in the pool that
    # would otherwise fail the next request with "no active connection".
    pool_pre_ping=True,
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


# Freemium quota columns added 2026-10-12; create_all never ALTERs existing
# tables, so SQLite deployments get them via these guarded ALTERs at boot.
_MIGRATION_COLUMNS = {
    "users": (
        ("free_requests_left", "INTEGER NOT NULL DEFAULT 3"),
        ("last_request_date", "TEXT"),
    ),
    "chat_sessions": (
        ("free_requests_left", "INTEGER NOT NULL DEFAULT 3"),
        ("last_request_date", "TEXT"),
    ),
}


async def _apply_sqlite_migrations(conn) -> None:
    for table, columns in _MIGRATION_COLUMNS.items():
        rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
        existing = {row[1] for row in rows}
        for name, ddl in columns:
            if name not in existing:
                await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


async def init_db() -> None:
    """Create tables on startup. For production PostgreSQL, prefer Alembic migrations."""
    from models import (  # noqa: F401
        ChatMessage,
        ChatSession,
        PremiumClaim,
        User,
        UserDocument,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "sqlite":
            await _apply_sqlite_migrations(conn)


async def get_db() -> AsyncSession:
    """FastAPI dependency yielding an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
