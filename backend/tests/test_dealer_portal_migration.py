"""Migration 0022 (dealer portal core).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0022 database (its own engine — the shared fixture
schema already carries the post-0022 shape) and pins:

- dealer_agent_profiles and dealer_company_representations are
  created with the columns the models declare;
- private_agents gains archived / linked_user_id / link_snapshot;
- preferred_agents gains switched_from_private_agent_id;
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
    / "0022_dealer_portal.py"
)

_NEW_TABLES = {"dealer_agent_profiles", "dealer_company_representations"}


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0022_dealer_portal", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0022_engine():
    """A database as of 0021: users + the dealers tables as 0016
    left them (no switch columns yet)."""
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
                "CREATE TABLE dealer_companies ("
                " id VARCHAR(36) PRIMARY KEY,"
                " owner_id VARCHAR(36),"
                " name VARCHAR(300) NOT NULL DEFAULT '',"
                " is_directory BOOLEAN NOT NULL DEFAULT 0"
                ")"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE private_agents ("
                " id VARCHAR(36) PRIMARY KEY,"
                " owner_id VARCHAR(36) NOT NULL,"
                " company_id VARCHAR(36),"
                " name VARCHAR(300) NOT NULL DEFAULT ''"
                ")"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE preferred_agents ("
                " id VARCHAR(36) PRIMARY KEY,"
                " user_id VARCHAR(36) NOT NULL,"
                " company_id VARCHAR(36) NOT NULL,"
                " agent_user_id VARCHAR(36),"
                " private_agent_id VARCHAR(36)"
                ")"
            )
        )
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_0022_upgrade_adds_portal_tables_and_switch_columns():
    migration = _load_migration()
    assert migration.revision == "0022_dealer_portal"
    assert migration.down_revision == "0021_claims"
    engine = _pre_0022_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        assert _NEW_TABLES <= set(inspector.get_table_names())

        profile_columns = {
            c["name"] for c in inspector.get_columns("dealer_agent_profiles")
        }
        assert {
            "user_id", "display_name", "phone", "contact_email",
            "service_area", "bio", "photo_key", "publicly_listed",
        } <= profile_columns

        rep_columns = {
            c["name"]
            for c in inspector.get_columns("dealer_company_representations")
        }
        assert {
            "agent_user_id", "company_id", "verified",
            "verified_by_id", "verified_at",
        } <= rep_columns
        uniques = inspector.get_unique_constraints(
            "dealer_company_representations"
        )
        assert any(
            set(u["column_names"]) == {"agent_user_id", "company_id"}
            for u in uniques
        )

        private_columns = {
            c["name"] for c in inspector.get_columns("private_agents")
        }
        assert {"archived", "linked_user_id", "link_snapshot"} <= private_columns
        preferred_columns = {
            c["name"] for c in inspector.get_columns("preferred_agents")
        }
        assert "switched_from_private_agent_id" in preferred_columns


def test_0022_downgrade_removes_exactly_what_upgrade_added():
    migration = _load_migration()
    engine = _pre_0022_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert not (_NEW_TABLES & tables)
        assert "users" in tables  # pre-existing data untouched
        private_columns = {
            c["name"] for c in inspector.get_columns("private_agents")
        }
        assert "archived" not in private_columns
        assert "linked_user_id" not in private_columns
        preferred_columns = {
            c["name"] for c in inspector.get_columns("preferred_agents")
        }
        assert "switched_from_private_agent_id" not in preferred_columns
