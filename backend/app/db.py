"""Async SQLAlchemy engine and session factory.

Default database: SQLite (one file, no server). The API and the worker processes share it, so it
runs in WAL mode (readers never block the writer) with a busy timeout (writers queue instead of
failing with "database is locked"). Any other SQLAlchemy URL in DATABASE_URL still works.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.app.settings import ROOT, get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")  # needed for ON DELETE CASCADE
    cursor.close()


def engine() -> AsyncEngine:
    global _engine, _sessions
    if _engine is None:
        url = make_url(get_settings().database_url)
        if url.get_backend_name() == "sqlite":
            if url.database and url.database != ":memory:":
                path = Path(url.database)
                if not path.is_absolute():  # same file whatever folder the API or worker is started from
                    path = ROOT / path
                    url = url.set(database=str(path))
                path.parent.mkdir(parents=True, exist_ok=True)
            _engine = create_async_engine(url, connect_args={"timeout": 30})
            event.listen(_engine.sync_engine, "connect", _sqlite_pragmas)
        else:
            _engine = create_async_engine(url, pool_pre_ping=True, pool_size=10)
        _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessions() -> async_sessionmaker[AsyncSession]:
    engine()
    assert _sessions is not None
    return _sessions


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessions()() as session:
        yield session


async def create_tables() -> None:
    from backend.app import models  # noqa: F401  (registers the tables)

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    global _engine, _sessions
    if _engine is not None:
        await _engine.dispose()
    _engine = _sessions = None
