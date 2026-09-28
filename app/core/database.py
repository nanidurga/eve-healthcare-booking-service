"""Engine, session factory and the declarative base."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base for every ORM model."""


def _engine_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"echo": False, "future": True}
    if not settings.is_sqlite:
        # Modest pool: this service is IO-bound and runs behind a single worker
        # in the reference deployment.
        kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)
    return kwargs


engine = create_async_engine(settings.database_url, **_engine_kwargs())

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep attributes readable after commit, for responses
    autoflush=False,
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    """SQLite ignores foreign keys unless asked; PostgreSQL never needs this."""
    if not settings.is_sqlite:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session.

    Commits are the service layer's responsibility — a request that only reads
    should not open a write transaction, and the webhook needs to control its
    own transaction boundary precisely.
    """
    session = SessionFactory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
