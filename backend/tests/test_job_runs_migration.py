"""Migration 0035 (background jobs ledger, step-4 fix round).

Runs the migration's real upgrade()/downgrade() against an empty
database and pins: the job_runs table lands with its columns and
indexes, and downgrade removes it.
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
    / "0035_job_runs.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0035", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _empty_db():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _run(engine, fn):
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            fn()
        conn.commit()


def test_upgrade_creates_job_runs_and_downgrade_drops_it():
    module = _load_migration()
    assert module.down_revision == "0034_forum"
    engine = _empty_db()
    _run(engine, module.upgrade)

    inspector = sa.inspect(engine)
    assert "job_runs" in set(inspector.get_table_names())
    columns = {c["name"] for c in inspector.get_columns("job_runs")}
    assert columns == {
        "id", "job", "started_at", "finished_at", "status", "detail",
    }
    indexes = {ix["name"] for ix in inspector.get_indexes("job_runs")}
    assert {"ix_job_runs_job", "ix_job_runs_started_at"} <= indexes

    _run(engine, module.downgrade)
    inspector = sa.inspect(engine)
    assert "job_runs" not in set(inspector.get_table_names())
