"""Migration 0031 (Package C — sharing rules + My Insurance).

Runs the migration's real upgrade()/downgrade() against a scratch
database and pins the shapes the build relies on: the four new
tables with their columns, and the claims agent-snapshot columns
(existing claims get empty strings — no backfill is honest).
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
    / "0031_pkgc_sharing_insurance.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0031_pkgc_sharing_insurance", _MIGRATION_PATH
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
        # The FK targets + the claims table the agent columns land on.
        conn.execute(sa.text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE tools (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(
            sa.text("CREATE TABLE batteries (id VARCHAR(36) PRIMARY KEY)")
        )
        conn.execute(sa.text("CREATE TABLE claims (id VARCHAR(36) PRIMARY KEY)"))
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_upgrade_creates_the_pkgc_tables_and_claim_columns():
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
    inspector = sa.inspect(engine)
    tables = inspector.get_table_names()
    for table in (
        "share_rules",
        "share_exclusions",
        "peer_share_exclusion_rules",
        "insurance_profiles",
    ):
        assert table in tables

    rule_columns = {
        c["name"] for c in inspector.get_columns("share_rules")
    }
    assert rule_columns == {
        "id",
        "owner_id",
        "recipient_group",
        "scope",
        "scope_value",
        "scope_ref_id",
        "include_addons",
        "created_at",
        "updated_at",
    }
    profile_columns = {
        c["name"] for c in inspector.get_columns("insurance_profiles")
    }
    assert profile_columns == {
        "id",
        "user_id",
        "insurer_company",
        "agent_name",
        "agent_phone",
        "agent_email",
        "policy_number",
        "notes",
        "created_at",
        "updated_at",
    }
    uniques = inspector.get_unique_constraints("insurance_profiles")
    assert any(set(u["column_names"]) == {"user_id"} for u in uniques)

    claim_columns = {c["name"] for c in inspector.get_columns("claims")}
    assert {"agent_name", "agent_phone", "agent_email"} <= claim_columns


def test_downgrade_drops_everything():
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
    inspector = sa.inspect(engine)
    tables = inspector.get_table_names()
    for table in (
        "share_rules",
        "share_exclusions",
        "peer_share_exclusion_rules",
        "insurance_profiles",
    ):
        assert table not in tables
    claim_columns = {c["name"] for c in inspector.get_columns("claims")}
    assert not ({"agent_name", "agent_phone", "agent_email"} & claim_columns)
