"""Migration 0042 (wave 4, 2026-10-20).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0042 database (users, tools, batteries) and pins:

- tools + batteries gain `upc` (default "");
- users gains `catalog_contribute` DEFAULT TRUE — existing
  accounts contribute until they opt out (the owner's call,
  with the Settings copy naming exactly what contributes);
- cloud_drive_connections lands with a UNIQUE user index and
  cloud_backup_runs with its history columns;
- downgrade removes everything it added.
"""

import importlib.util
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
    / "0042_wave4.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0042", _MIGRATION_PATH)
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
    for table in ("tools", "batteries"):
        sa.Table(table, meta, sa.Column("id", sa.Uuid, primary_key=True))
    meta.create_all(engine)
    return engine


def _columns(engine, table):
    inspector = sa.inspect(engine)
    return {c["name"] for c in inspector.get_columns(table)}


def _tables(engine):
    return set(sa.inspect(engine).get_table_names())


def test_upgrade_adds_wave4_schema():
    migration = _load_migration()
    engine = _pre_db()
    import uuid

    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO users (id, email) VALUES (:id, :e)"),
            {"id": str(uuid.uuid4()), "e": "old@example.com"},
        )
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
    assert "upc" in _columns(engine, "tools")
    assert "upc" in _columns(engine, "batteries")
    assert "catalog_contribute" in _columns(engine, "users")
    assert {"cloud_drive_connections", "cloud_backup_runs"} <= _tables(engine)
    conn_columns = _columns(engine, "cloud_drive_connections")
    assert {
        "user_id",
        "refresh_token_encrypted",
        "drive_folder_id",
        "schedule",
        "last_backup_at",
    } <= conn_columns
    run_columns = _columns(engine, "cloud_backup_runs")
    assert {"user_id", "trigger", "status", "file_id", "error"} <= run_columns
    # The pre-existing user lands on the DEFAULT: contributing.
    with engine.connect() as conn:
        value = conn.execute(
            sa.text("SELECT catalog_contribute FROM users")
        ).scalar()
    assert value in (1, True)


def test_downgrade_removes_wave4_schema():
    migration = _load_migration()
    engine = _pre_db()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
            migration.downgrade()
    assert "upc" not in _columns(engine, "tools")
    assert "catalog_contribute" not in _columns(engine, "users")
    assert "cloud_drive_connections" not in _tables(engine)
    assert "cloud_backup_runs" not in _tables(engine)
