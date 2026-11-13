"""Migration 0071 (rail pin, widget options Wave 1, 2026-11-02).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0071 database (a bare users table) and pins:

- users gains `rail_pinned`, NULLABLE, with no default filled
  in — a pre-existing account's row reads NULL ("never set"),
  which the client reads as unpinned;
- downgrade removes exactly the column it added.
"""

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0071_rail_pinned.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0071", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("email", sa.String(320)),
    )
    meta.create_all(engine)
    return engine


def _columns(engine, table):
    inspector = sa.inspect(engine)
    return {c["name"]: c for c in inspector.get_columns(table)}


def test_upgrade_adds_nullable_rail_pinned_and_existing_rows_read_null():
    migration = _load_migration()
    engine = _pre_db()
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO users (id, email) VALUES (:id, :e)"),
            {"id": str(uuid.uuid4()), "e": "old@example.com"},
        )
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
    columns = _columns(engine, "users")
    assert "rail_pinned" in columns
    assert columns["rail_pinned"]["nullable"] is True
    with engine.connect() as conn:
        value = conn.execute(
            sa.text("SELECT rail_pinned FROM users")
        ).scalar()
    assert value is None


def test_downgrade_removes_rail_pinned():
    migration = _load_migration()
    engine = _pre_db()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
            migration.downgrade()
    assert "rail_pinned" not in _columns(engine, "users")
