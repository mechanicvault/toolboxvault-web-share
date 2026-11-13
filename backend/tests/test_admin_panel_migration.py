"""Migration 0011 (admin panel, Phase A2).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0011 database (its own engine — the shared fixture
schema already carries the post-0011 shape) and pins:

- users gains role + is_active, and an existing account lands on
  role="user" / is_active=true from the server defaults;
- banned_emails and audit_log are created;
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
    / "0011_admin_panel.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0011_admin_panel", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0011_engine():
    """A database as of 0010: a users table WITHOUT role/is_active
    and no ban/audit tables, holding one account."""
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
                " email VARCHAR(320) NOT NULL,"
                " name VARCHAR(200) NOT NULL DEFAULT '',"
                " password_hash VARCHAR(255) NOT NULL DEFAULT '',"
                " account_types JSON NOT NULL DEFAULT '[]'"
                ")"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO users (id, account_number, email, name)"
                " VALUES ('u-1', 'TV-M-000001', 'legacy@example.com', 'Legacy')"
            )
        )
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_0011_upgrade_adds_columns_tables_and_defaults():
    migration = _load_migration()
    engine = _pre_0011_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        user_columns = {c["name"] for c in inspector.get_columns("users")}
        assert {"role", "is_active"} <= user_columns
        tables = set(inspector.get_table_names())
        assert {"banned_emails", "audit_log"} <= tables
        row = conn.execute(
            sa.text("SELECT role, is_active FROM users WHERE id = 'u-1'")
        ).one()
        assert row[0] == "user"
        assert row[1] in (1, True)


def test_0011_downgrade_removes_exactly_what_upgrade_added():
    migration = _load_migration()
    engine = _pre_0011_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        user_columns = {c["name"] for c in inspector.get_columns("users")}
        assert "role" not in user_columns
        assert "is_active" not in user_columns
        tables = set(inspector.get_table_names())
        assert "banned_emails" not in tables
        assert "audit_log" not in tables
        # The account itself survives the round trip.
        count = conn.execute(sa.text("SELECT COUNT(*) FROM users")).scalar()
        assert count == 1
