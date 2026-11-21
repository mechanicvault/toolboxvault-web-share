"""Migration 0020 (maintenance module).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0020 database (its own engine — the shared fixture
schema already carries the post-0020 shape) and pins:

- tools gains warranty_months + the repair standing columns;
  batteries and set_pieces gain the repair standing columns;
- existing rows land on repair_state='in_service' /
  repair_problem='' from the server defaults;
- repair_records, maintenance_schedules and
  maintenance_log_entries are created;
- downgrade removes exactly what upgrade added.
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
    / "0020_maintenance.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0020_maintenance", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0020_engine():
    """A database as of 0019: tools/batteries/set_pieces WITHOUT
    the maintenance columns and none of the new tables."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        for table in ("tools", "batteries", "set_pieces"):
            conn.execute(
                sa.text(
                    f"CREATE TABLE {table} ("
                    " id VARCHAR(36) PRIMARY KEY,"
                    " name VARCHAR(200) NOT NULL DEFAULT ''"
                    ")"
                )
            )
            conn.execute(
                sa.text(f"INSERT INTO {table} (id, name) VALUES ('x-1', 'Legacy')")
            )
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_0020_upgrade_adds_columns_tables_and_defaults():
    migration = _load_migration()
    engine = _pre_0020_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        tool_columns = {c["name"] for c in inspector.get_columns("tools")}
        assert {"warranty_months", "repair_state", "repair_problem"} <= tool_columns
        for table in ("batteries", "set_pieces"):
            columns = {c["name"] for c in inspector.get_columns(table)}
            assert {"repair_state", "repair_problem"} <= columns
        tables = set(inspector.get_table_names())
        assert {
            "repair_records",
            "maintenance_schedules",
            "maintenance_log_entries",
        } <= tables
        for table in ("tools", "batteries", "set_pieces"):
            row = conn.execute(
                sa.text(f"SELECT repair_state, repair_problem FROM {table}")
            ).one()
            assert row[0] == "in_service"
            assert row[1] == ""


def test_0020_downgrade_removes_exactly_what_upgrade_added():
    migration = _load_migration()
    engine = _pre_0020_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        tool_columns = {c["name"] for c in inspector.get_columns("tools")}
        assert "warranty_months" not in tool_columns
        assert "repair_state" not in tool_columns
        tables = set(inspector.get_table_names())
        assert "repair_records" not in tables
        assert "maintenance_schedules" not in tables
        assert "maintenance_log_entries" not in tables
        # The pre-existing rows survive the round trip.
        count = conn.execute(sa.text("SELECT COUNT(*) FROM tools")).scalar()
        assert count == 1
