"""Centralized database access.

The ONLY place the engine and sessions are created. Modules get a Session
via the `get_db` dependency — they never create engines or sessions.
Sync SQLAlchemy 2.0 style, kept readable on purpose.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """All module models inherit from this."""


# Pool sizing (scale fix, 2026-10-26): explicit, settings-driven —
# see core/config.py for the CX23 budget math. Pool arguments are
# QueuePool-only, so they apply solely to the Postgres DSN the
# app actually runs on; any other URL (a dev SQLite file) keeps
# its dialect defaults untouched.
_pool_kwargs: dict = {}
if settings.database_url.startswith("postgresql"):
    _pool_kwargs = {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_recycle": settings.db_pool_recycle_seconds,
    }

engine = create_engine(settings.database_url, pool_pre_ping=True, **_pool_kwargs)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session, closes it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
