"""Migration 0012 (email flows).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0012 database (its own engine — the shared fixture
schema already carries the post-0012 shape) and pins:

- email_outbox, password_reset_tokens, and email_change_tokens
  are created with their expected columns;
- email_change_tokens carries new_email (the pending state);
- the chain revises 0011;
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
    / "0012_email_flows.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0012_email_flows", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0012_engine():
    """A database as of 0011: a users table (the new tables
    reference it by FK) and none of the email-flow tables."""
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
                " account_number VARCHAR(16) NOT NULL,"
                " email VARCHAR(320) NOT NULL"
                ")"
            )
        )
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_0012_chain_revises_0011():
    migration = _load_migration()
    assert migration.revision == "0012_email_flows"
    assert migration.down_revision == "0011_admin_panel"


def test_0012_upgrade_creates_the_three_tables():
    migration = _load_migration()
    engine = _pre_0012_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert {
            "email_outbox",
            "password_reset_tokens",
            "email_change_tokens",
        } <= tables
        outbox_columns = {c["name"] for c in inspector.get_columns("email_outbox")}
        assert {
            "recipient",
            "subject",
            "kind",
            "body",
            "provider",
            "status",
            "created_at",
        } <= outbox_columns
        change_columns = {c["name"] for c in inspector.get_columns("email_change_tokens")}
        assert {"user_id", "new_email", "token_hash", "expires_at", "used_at"} <= change_columns
        reset_columns = {c["name"] for c in inspector.get_columns("password_reset_tokens")}
        assert {"user_id", "token_hash", "expires_at", "used_at"} <= reset_columns


def test_0012_downgrade_removes_exactly_what_upgrade_added():
    migration = _load_migration()
    engine = _pre_0012_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
        tables = set(sa.inspect(conn).get_table_names())
        assert "email_outbox" not in tables
        assert "password_reset_tokens" not in tables
        assert "email_change_tokens" not in tables
