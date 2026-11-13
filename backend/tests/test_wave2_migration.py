"""Migration 0040 (Wave 2) upgrades a 0039-shaped database
cleanly: the four new tables (wishlist_items, sale_records,
truck_accounts, truck_entries) appear, the dealer agent profile
gains its four Connect columns defaulting dark (no account id,
charges/payouts off, onboarding not started), and the downgrade
removes exactly what the upgrade added."""

import importlib.util
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0040_wave2.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0040", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0040 shape: the tables the migration touches
    around — users (FK target), dealer_companies (FK target),
    dealer_agent_profiles (the altered table)."""
    meta = MetaData()
    Table(
        "users",
        meta,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("email", String(300), nullable=False),
    )
    Table(
        "dealer_companies",
        meta,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("name", String(300), nullable=False),
    )
    Table(
        "dealer_agent_profiles",
        meta,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        Column("publicly_listed", Boolean, nullable=False),
        Column("created_at", DateTime(timezone=True)),
    )
    meta.create_all(engine)


def test_migration_0040_upgrade_and_downgrade():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = create_engine("sqlite://")
    _pre_state(engine)
    module = _load_migration()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()
        tables = set(inspect(conn).get_table_names())
        assert {
            "wishlist_items",
            "sale_records",
            "truck_accounts",
            "truck_entries",
        } <= tables
        cols = {
            c["name"] for c in inspect(conn).get_columns("dealer_agent_profiles")
        }
        assert {
            "stripe_connect_account_id",
            "connect_charges_enabled",
            "connect_payouts_enabled",
            "connect_onboarding_state",
        } <= cols
        sale_cols = {c["name"] for c in inspect(conn).get_columns("sale_records")}
        assert "seq" in sale_cols
        conn.execute(text("INSERT INTO users (id, email) VALUES ('u1', 'a@x.com')"))
        conn.execute(
            text(
                "INSERT INTO dealer_agent_profiles"
                " (id, user_id, publicly_listed) VALUES ('p1', 'u1', 0)"
            )
        )
        row = conn.execute(
            text(
                "SELECT stripe_connect_account_id, connect_charges_enabled,"
                " connect_payouts_enabled, connect_onboarding_state"
                " FROM dealer_agent_profiles"
            )
        ).one()
        # (SQLite stores the text server_default verbatim; the ORM
        # reads it back as a real False on both dialects.)
        assert row[0] is None
        assert row[1] in (0, False, "false") and row[2] in (0, False, "false")
        assert row[3] == "not_started"
        with Operations.context(ctx):
            module.downgrade()
        tables = set(inspect(conn).get_table_names())
        assert "wishlist_items" not in tables
        assert "sale_records" not in tables
        assert "truck_accounts" not in tables
        assert "truck_entries" not in tables
        cols = {
            c["name"] for c in inspect(conn).get_columns("dealer_agent_profiles")
        }
        assert "stripe_connect_account_id" not in cols
