"""Migration 0041 (Wave 3) upgrades a 0040-shaped database
cleanly: users gain country + currency, the crew / insurer /
FX / feedback tables appear, insurance_profiles gains the
directory link, claims gain archive shelving and claim_lines
the package toggle — and the downgrade removes exactly what
the upgrade added."""

import importlib.util
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0041_wave3.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0041", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0041 shape: the tables the migration alters
    (users, insurance_profiles, claims, claim_lines)."""
    meta = MetaData()
    Table(
        "users",
        meta,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("email", String(300), nullable=False),
    )
    Table(
        "insurance_profiles",
        meta,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        Column("created_at", DateTime(timezone=True)),
    )
    Table(
        "claims",
        meta,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("claim_number", String(50), nullable=False),
    )
    Table(
        "claim_lines",
        meta,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("claim_id", PG_UUID(as_uuid=True), nullable=False),
    )
    meta.create_all(engine)


def _columns(conn, table):
    return {c["name"] for c in inspect(conn).get_columns(table)}


def test_migration_0041_upgrade_and_downgrade():
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
            "shop_memberships",
            "insurer_companies",
            "insurer_affiliations",
            "fx_rates",
            "feedback_posts",
            "feedback_votes",
            "feedback_comments",
            "feedback_reports",
        } <= tables
        assert {"country", "currency"} <= _columns(conn, "users")
        assert "insurer_company_id" in _columns(conn, "insurance_profiles")
        assert {"archived", "archived_at"} <= _columns(conn, "claims")
        assert "include_in_package" in _columns(conn, "claim_lines")

        with Operations.context(ctx):
            module.downgrade()
        tables = set(inspect(conn).get_table_names())
        assert not {
            "shop_memberships",
            "insurer_companies",
            "insurer_affiliations",
            "fx_rates",
            "feedback_posts",
            "feedback_votes",
            "feedback_comments",
            "feedback_reports",
        } & tables
        assert "country" not in _columns(conn, "users")
        assert "insurer_company_id" not in _columns(conn, "insurance_profiles")
        assert "archived" not in _columns(conn, "claims")
        assert "include_in_package" not in _columns(conn, "claim_lines")
