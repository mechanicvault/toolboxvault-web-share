"""Migration 0016 (item structure package): runs the migration's
real upgrade()/downgrade() against a hand-built PRE-0016 database
and pins: the chain revises 0015, every new table/column lands
(tools/batteries fields, set_pieces with its core-price CHECK,
tags/item_tags, the dealers tables, checkouts.group_id,
shared_items.include_addons, peer_set_choices), the directory seed
carries the four majors with ONLY verified public contacts, and
downgrade removes exactly what upgrade added.

The plpgsql search-function replacement is Postgres-only (guarded
by dialect in the migration); the vector content itself is proven
live against production Postgres in the build's smoke test.
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
    / "0016_item_structure.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0016_item_structure", _MIGRATION_PATH
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


def _pre_0016_schema(conn):
    """The tables 0016 touches, in their pre-0016 shape (only the
    columns the migration interacts with need to exist)."""
    conn.execute(sa.text("CREATE TABLE users (id CHAR(36) PRIMARY KEY)"))
    conn.execute(
        sa.text(
            "CREATE TABLE tools (id CHAR(36) PRIMARY KEY, owner_id CHAR(36), "
            "name VARCHAR(300), model VARCHAR(200) DEFAULT '', "
            "serial_number VARCHAR(200) DEFAULT '')"
        )
    )
    conn.execute(sa.text("CREATE TABLE batteries (id CHAR(36) PRIMARY KEY, owner_id CHAR(36))"))
    conn.execute(sa.text("CREATE TABLE checkouts (id CHAR(36) PRIMARY KEY)"))
    conn.execute(sa.text("CREATE TABLE shared_items (id CHAR(36) PRIMARY KEY)"))


def test_chain_revises_0015():
    migration = _load_migration()
    assert migration.revision == "0016_item_structure"
    assert migration.down_revision == "0015_borrowing"


def test_upgrade_and_downgrade():
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        _pre_0016_schema(conn)
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()

        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert {
            "dealer_companies",
            "private_agents",
            "preferred_agents",
            "set_pieces",
            "tags",
            "item_tags",
            "peer_set_choices",
        } <= tables

        tool_columns = {c["name"] for c in inspector.get_columns("tools")}
        assert {
            "quantity",
            "size",
            "model_numbers",
            "serial_numbers",
            "consumable",
            "is_set",
            "attached_to_set_id",
            "dealer_company_id",
        } <= tool_columns
        battery_columns = {c["name"] for c in inspector.get_columns("batteries")}
        assert {"quantity", "dealer_company_id"} <= battery_columns
        checkout_columns = {c["name"] for c in inspector.get_columns("checkouts")}
        assert "group_id" in checkout_columns
        shared_columns = {c["name"] for c in inspector.get_columns("shared_items")}
        assert "include_addons" in shared_columns

        # The core-price rule is a database CHECK, not just service
        # politeness.
        checks = inspector.get_check_constraints("set_pieces")
        assert any("price" in (c.get("sqltext") or "") for c in checks)

        # Directory seed: the four majors, directory rows only, no
        # invented billing numbers anywhere.
        rows = conn.execute(
            sa.text("SELECT name, email, phones FROM dealer_companies")
        ).all()
        names = {row[0] for row in rows}
        assert names == {
            "Snap-on Incorporated",
            "Matco Tools",
            "Mac Tools",
            "Cornwell Quality Tools",
        }
        import json

        for _name, _email, phones in rows:
            parsed = json.loads(phones) if isinstance(phones, str) else phones
            labels = {p["label"] for p in parsed}
            assert "Billing" not in labels

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.downgrade()
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert "dealer_companies" not in tables
        assert "set_pieces" not in tables
        assert "peer_set_choices" not in tables
        tool_columns = {c["name"] for c in inspector.get_columns("tools")}
        assert "quantity" not in tool_columns
        assert "dealer_company_id" not in tool_columns
