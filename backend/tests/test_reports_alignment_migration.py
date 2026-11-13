"""Migration 0032 (reports alignment): users gain the report
contact fields (phone, postal_address), report_configs gains the
options bag — upgrade shapes pinned, downgrade removes them."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _load_migration():
    path = VERSIONS / "0032_reports_alignment.py"
    spec = importlib.util.spec_from_file_location("migration_0032", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine():
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(
            sa.text("CREATE TABLE report_configs (id VARCHAR(36) PRIMARY KEY)")
        )
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_upgrade_adds_profile_fields_and_options_bag():
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
    inspector = sa.inspect(engine)
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    assert {"phone", "postal_address"} <= user_columns
    config_columns = {c["name"] for c in inspector.get_columns("report_configs")}
    assert "options" in config_columns


def test_downgrade_removes_them():
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
    inspector = sa.inspect(engine)
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    assert "phone" not in user_columns
    assert "postal_address" not in user_columns
    config_columns = {c["name"] for c in inspector.get_columns("report_configs")}
    assert "options" not in config_columns
