"""Migration 0028 (messaging + community parts pool).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0028 database (users + parts only — the tables it
touches beyond creating its own) and pins:

- users gain the contact preferences with SAFE defaults on
  existing rows (empty area/phone, show_phone OFF — nobody's
  number becomes public by a deploy);
- parts gain the pool columns, all nullable/defaulted so every
  existing part resolves PRIVATE (opt-in is a user act);
- the six new tables land (part_pool_settings, message_threads,
  messages, message_thread_states, user_blocks,
  message_reports);
- downgrade removes everything it added.
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
    / "0028_messaging_pool.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0028", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    meta = sa.MetaData()
    users = sa.Table(
        "users",
        meta,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("email", sa.String(320)),
    )
    parts = sa.Table(
        "parts",
        meta,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("owner_id", sa.Uuid),
        sa.Column("title", sa.String(300)),
    )
    meta.create_all(engine)
    user_id = uuid.uuid4()
    part_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(users.insert().values(id=user_id, email="a@example.com"))
        conn.execute(
            parts.insert().values(id=part_id, owner_id=user_id, title="Old part")
        )
    return engine, users, parts, user_id, part_id


def _run(engine, fn):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            fn()
        conn.commit()


def test_upgrade_adds_columns_with_safe_defaults_and_tables():
    migration = _load_migration()
    engine, users, parts, user_id, part_id = _pre_db()
    _run(engine, migration.upgrade)

    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "part_pool_settings",
        "message_threads",
        "messages",
        "message_thread_states",
        "user_blocks",
        "message_reports",
    } <= tables

    # Reflect fresh table shapes — the pre-migration Table
    # objects above don't know the new columns exist.
    meta = sa.MetaData()
    users = sa.Table("users", meta, autoload_with=engine)
    parts = sa.Table("parts", meta, autoload_with=engine)
    with engine.connect() as conn:
        user = conn.execute(sa.select(users)).mappings().one()
        assert user["public_area_label"] == ""
        assert user["contact_phone"] == ""
        assert user["show_phone"] in (0, False)
        part = conn.execute(sa.select(parts)).mappings().one()
        assert part["year"] is None
        assert part["make"] == "" and part["model"] == "" and part["engine"] == ""
        assert part["category"] == ""
        assert part["asking_price"] is None
        # PRIVATE by construction: no override, no settings row.
        assert part["visibility"] is None
        assert part["show_phone_override"] is None


def test_downgrade_removes_everything():
    migration = _load_migration()
    engine, users, parts, user_id, part_id = _pre_db()
    _run(engine, migration.upgrade)
    _run(engine, migration.downgrade)

    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert "message_threads" not in tables
    assert "part_pool_settings" not in tables
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    assert "contact_phone" not in user_columns
    part_columns = {c["name"] for c in inspector.get_columns("parts")}
    assert "visibility" not in part_columns and "year" not in part_columns
