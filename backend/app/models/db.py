from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings

SessionFactory = async_sessionmaker[AsyncSession]


def make_engine(settings: Settings) -> AsyncEngine:
    url = settings.database_url
    if url.startswith("sqlite"):
        engine = create_async_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - sqlite only
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=5)


def make_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)
