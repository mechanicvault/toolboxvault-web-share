"""Migration 0029 (Package B — inventory organization).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0029 database (its own engine — the shared fixture
schema already carries the post-0029 shape) and pins:

- inventory_locations is created with its owner + parent FKs;
- tools/batteries gain location_id (FK, SET NULL) and standing;
- the BACKFILL: each owner's distinct free-text locations become
  top-level nodes and their items link to them; standing starts as
  the item's repair_state;
- maintenance_log_entries gains the attachments column;
- downgrade removes exactly what upgrade added.
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
    / "0029_pkgb_inventory_org.py"
)

OWNER_A = str(uuid.uuid4())
OWNER_B = str(uuid.uuid4())
TOOL_1 = str(uuid.uuid4())
TOOL_2 = str(uuid.uuid4())
TOOL_3 = str(uuid.uuid4())
BATT_1 = str(uuid.uuid4())


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0029_pkgb", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0029_engine():
    """A database as of 0028: users, tools + batteries carrying
    free-text locations and repair states, maintenance log entries.
    Two owners share a location NAME (nodes must stay per-owner)
    and one item has no location at all (no node, no link)."""
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
                " email VARCHAR(320) NOT NULL DEFAULT '')"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE tools ("
                " id VARCHAR(36) PRIMARY KEY,"
                " owner_id VARCHAR(36) NOT NULL,"
                " name VARCHAR(200) NOT NULL DEFAULT '',"
                " location VARCHAR(200) NOT NULL DEFAULT '',"
                " repair_state VARCHAR(20) NOT NULL DEFAULT 'in_service')"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE batteries ("
                " id VARCHAR(36) PRIMARY KEY,"
                " owner_id VARCHAR(36) NOT NULL,"
                " name VARCHAR(200) NOT NULL DEFAULT '',"
                " location VARCHAR(200) NOT NULL DEFAULT '',"
                " repair_state VARCHAR(20) NOT NULL DEFAULT 'in_service')"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE maintenance_log_entries ("
                " id VARCHAR(36) PRIMARY KEY,"
                " notes TEXT NOT NULL DEFAULT '')"
            )
        )
        for uid in (OWNER_A, OWNER_B):
            conn.execute(
                sa.text("INSERT INTO users (id, email) VALUES (:id, '')"),
                {"id": uid},
            )
        rows = [
            # (table, id, owner, location, repair_state)
            ("tools", TOOL_1, OWNER_A, "Shop Toolbox", "broken"),
            ("tools", TOOL_2, OWNER_A, "Shop Toolbox", "in_service"),
            ("tools", TOOL_3, OWNER_A, "", "in_repair"),
            ("batteries", BATT_1, OWNER_B, "Shop Toolbox", "in_service"),
        ]
        for table, rid, owner, location, state in rows:
            conn.execute(
                sa.text(
                    f"INSERT INTO {table} (id, owner_id, name, location, repair_state)"
                    " VALUES (:id, :owner, 'x', :loc, :state)"
                ),
                {"id": rid, "owner": owner, "loc": location, "state": state},
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


def test_migration_0029_schema_and_backfill():
    migration = _load_migration()
    assert migration.revision == "0029_pkgb_inventory_org"
    assert migration.down_revision == "0028_messaging_pool"

    engine = _pre_0029_engine()
    _run(engine, migration, "up")

    inspector = sa.inspect(engine)
    assert "inventory_locations" in inspector.get_table_names()
    node_fks = {
        (fk["referred_table"], tuple(fk["constrained_columns"]))
        for fk in inspector.get_foreign_keys("inventory_locations")
    }
    assert ("users", ("owner_id",)) in node_fks
    assert ("inventory_locations", ("parent_id",)) in node_fks

    tool_columns = {c["name"] for c in inspector.get_columns("tools")}
    assert {"location_id", "standing"} <= tool_columns
    tool_fks = {
        (fk["referred_table"], tuple(fk["constrained_columns"]), fk["options"].get("ondelete"))
        for fk in inspector.get_foreign_keys("tools")
    }
    assert ("inventory_locations", ("location_id",), "SET NULL") in tool_fks
    log_columns = {
        c["name"] for c in inspector.get_columns("maintenance_log_entries")
    }
    assert "attachments" in log_columns

    with engine.connect() as conn:
        nodes = conn.execute(
            sa.text(
                "SELECT id, owner_id, parent_id, name FROM inventory_locations"
            )
        ).fetchall()
        # Two owners, the same place name -> two separate top-level
        # nodes (the tree is owner-scoped, like everything else).
        assert len(nodes) == 2
        assert all(n[2] is None and n[3] == "Shop Toolbox" for n in nodes)
        # SQLite stores the PG UUID type as undashed hex — normalize
        # both sides before comparing ids.
        by_owner = {n[1].replace("-", ""): n[0] for n in nodes}
        by_owner = {OWNER_A: by_owner[OWNER_A.replace("-", "")],
                    OWNER_B: by_owner[OWNER_B.replace("-", "")]}

        tools = {
            r[0]: (r[1].replace("-", "") if r[1] else None, r[2])
            for r in conn.execute(
                sa.text("SELECT id, location_id, standing FROM tools")
            ).fetchall()
        }
        by_owner = {
            owner: node_id.replace("-", "")
            for owner, node_id in by_owner.items()
        }
        assert tools[TOOL_1] == (by_owner[OWNER_A], "broken")
        assert tools[TOOL_2] == (by_owner[OWNER_A], "in_service")
        assert tools[TOOL_3] == (None, "in_repair")  # unfiled stays unfiled
        batt = conn.execute(
            sa.text(
                "SELECT location_id, standing FROM batteries WHERE id = :id"
            ),
            {"id": BATT_1},
        ).fetchone()
        assert (batt[0].replace("-", ""), batt[1]) == (
            by_owner[OWNER_B],
            "in_service",
        )


def test_migration_0029_downgrade_removes_exactly_its_changes():
    migration = _load_migration()
    engine = _pre_0029_engine()
    _run(engine, migration, "up")
    _run(engine, migration, "down")

    inspector = sa.inspect(engine)
    assert "inventory_locations" not in inspector.get_table_names()
    tool_columns = {c["name"] for c in inspector.get_columns("tools")}
    assert "location_id" not in tool_columns
    assert "standing" not in tool_columns
    log_columns = {
        c["name"] for c in inspector.get_columns("maintenance_log_entries")
    }
    assert "attachments" not in log_columns
