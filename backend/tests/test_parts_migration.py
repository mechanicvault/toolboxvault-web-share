"""Migration 0026 (Used Parts module).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0026 database (its own engine — the shared fixture
schema already carries the post-0026 shape) and pins:

- part_locations and parts are created with the FKs the module
  relies on (owner, parent, location SET NULL, converted-tool
  SET NULL) and the quantity CHECK;
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
    / "0026_parts.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0026_parts", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0026_engine():
    """A database as of 0025: users + tools exist (parts references
    both), part_locations/parts do not."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE users ("
                " id VARCHAR(36) PRIMARY KEY,"
                " email VARCHAR(320) NOT NULL DEFAULT ''"
                ")"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE tools ("
                " id VARCHAR(36) PRIMARY KEY,"
                " name VARCHAR(200) NOT NULL DEFAULT ''"
                ")"
            )
        )
    return engine


def _run(engine, migration, direction):
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            if direction == "up":
                migration.upgrade()
            else:
                migration.downgrade()


def test_migration_0026_creates_the_parts_tables():
    migration = _load_migration()
    assert migration.revision == "0026_parts"
    assert migration.down_revision == "0025_corporate_directory"

    engine = _pre_0026_engine()
    _run(engine, migration, "up")

    inspector = sa.inspect(engine)
    assert "part_locations" in inspector.get_table_names()
    assert "parts" in inspector.get_table_names()

    location_columns = {
        c["name"] for c in inspector.get_columns("part_locations")
    }
    assert location_columns == {
        "id",
        "owner_id",
        "parent_id",
        "name",
        "level",
        "created_at",
        "updated_at",
    }
    location_fks = {
        (fk["referred_table"], tuple(fk["constrained_columns"]))
        for fk in inspector.get_foreign_keys("part_locations")
    }
    assert ("users", ("owner_id",)) in location_fks
    assert ("part_locations", ("parent_id",)) in location_fks

    part_columns = {c["name"] for c in inspector.get_columns("parts")}
    assert part_columns == {
        "id",
        "owner_id",
        "title",
        "quantity",
        "condition",
        "notes",
        "location_id",
        "custom_data",
        "attachments",
        "converted_tool_id",
        "created_at",
        "updated_at",
    }
    part_fks = {
        (fk["referred_table"], tuple(fk["constrained_columns"]))
        for fk in inspector.get_foreign_keys("parts")
    }
    assert ("users", ("owner_id",)) in part_fks
    assert ("part_locations", ("location_id",)) in part_fks
    assert ("tools", ("converted_tool_id",)) in part_fks
    checks = {
        check["name"] for check in inspector.get_check_constraints("parts")
    }
    assert "ck_parts_quantity_min" in checks


def test_migration_0026_downgrade_removes_exactly_its_tables():
    migration = _load_migration()
    engine = _pre_0026_engine()
    _run(engine, migration, "up")
    _run(engine, migration, "down")

    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert "parts" not in tables
    assert "part_locations" not in tables
    # The pre-existing tables are untouched.
    assert {"users", "tools"} <= tables
