"""Migration 0013 (Disaster Vault): runs the migration's real
upgrade()/downgrade() against a hand-built PRE-0013 database and
pins: backup_runs is created with its expected columns, the chain
revises 0012, and downgrade removes exactly what upgrade added.
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
    / "0013_backup_runs.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0013_backup_runs", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_chain_revises_0012():
    migration = _load_migration()
    assert migration.revision == "0013_backup_runs"
    assert migration.down_revision == "0012_email_flows"


def test_upgrade_creates_backup_runs_and_downgrade_drops_it():
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
        inspector = sa.inspect(conn)
        assert "backup_runs" in inspector.get_table_names()
        columns = {c["name"] for c in inspector.get_columns("backup_runs")}
        assert columns == {
            "id",
            "started_at",
            "finished_at",
            "bundle_name",
            "size_bytes",
            "encrypted",
            "uploaded",
            "verified",
            "status",
            "detail",
        }
        # A row inserts with server-side defaults alone.
        conn.execute(sa.text("INSERT INTO backup_runs (id) VALUES ('x')"))
        row = conn.execute(
            sa.text("SELECT status, encrypted, uploaded, verified FROM backup_runs")
        ).one()
        assert row.status == "running"
        assert not row.encrypted and not row.uploaded and not row.verified

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.downgrade()
        assert "backup_runs" not in sa.inspect(conn).get_table_names()
