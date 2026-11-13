"""Migration 0030 (importer smart value matching — learned answers).

Runs the migration's real upgrade()/downgrade() against an empty
scratch database and pins the table shape the matching engine
relies on: the columns, the (owner, field, normalized) uniqueness
that makes a learned answer one-row-per-value, and a clean
downgrade.
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
    / "0030_import_value_matching.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0030_import_value_matching", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        # The FK target: a minimal users table.
        conn.execute(sa.text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_upgrade_creates_the_learned_mappings_table():
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
    inspector = sa.inspect(engine)
    assert "import_value_mappings" in inspector.get_table_names()
    columns = {
        column["name"] for column in inspector.get_columns("import_value_mappings")
    }
    assert columns == {
        "id",
        "owner_id",
        "field",
        "raw_value",
        "normalized",
        "action",
        "target_id",
        "target_value",
        "created_at",
        "updated_at",
    }
    uniques = inspector.get_unique_constraints("import_value_mappings")
    assert any(
        set(u["column_names"]) == {"owner_id", "field", "normalized"}
        for u in uniques
    )


def test_downgrade_drops_the_table():
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
    inspector = sa.inspect(engine)
    assert "import_value_mappings" not in inspector.get_table_names()
