"""Migration 0027 (user audit trail + restore).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0027 database and pins:

- the three tables land (change_journal, restore_markers,
  retained_files) with the journal's ordering index;
- every EXISTING account gets exactly one baseline marker at
  journal_seq 0 (the journal starts empty — there is no history
  before this deploy);
- `audit.retention_days` seeds to 180 — and an operator value
  already present is never stomped;
- downgrade drops the tables and the seeded setting.
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
    / "0027_audit_trail.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0027", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_db(*, with_setting: int | None = None, user_count: int = 3):
    """A minimal pre-0027 schema: users + system_settings only —
    the two tables the upgrade touches beyond creating its own."""
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
    settings = sa.Table(
        "system_settings",
        meta,
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("value", sa.JSON),
    )
    meta.create_all(engine)
    user_ids = [uuid.uuid4() for _ in range(user_count)]
    with engine.begin() as conn:
        for uid in user_ids:
            conn.execute(users.insert().values(id=uid, email=f"{uid}@x.com"))
        if with_setting is not None:
            conn.execute(
                settings.insert().values(
                    key="audit.retention_days", value=with_setting
                )
            )
    return engine, user_ids


def _run(engine, fn):
    # engine.begin(): the migration's work commits with the block
    # (the suite's migration-test pattern).
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            fn()


def test_upgrade_creates_tables_baselines_and_setting():
    migration = _load_migration()
    engine, user_ids = _pre_db()
    _run(engine, migration.upgrade)

    inspector = sa.inspect(engine)
    assert {"change_journal", "restore_markers", "retained_files"} <= set(
        inspector.get_table_names()
    )
    journal_cols = {
        c["name"] for c in inspector.get_columns("change_journal")
    }
    assert {
        "id", "seq", "user_id", "occurred_at", "module", "entity_type",
        "entity_id", "action", "before", "after", "actor_id",
        "marker_id", "restorable", "label",
    } <= journal_cols
    index_names = {
        ix["name"] for ix in inspector.get_indexes("change_journal")
    }
    assert "ix_change_journal_user_seq" in index_names

    with engine.connect() as conn:
        markers = conn.execute(
            sa.text(
                "SELECT user_id, kind, journal_seq, label FROM restore_markers"
            )
        ).all()
        setting = conn.execute(
            sa.text(
                "SELECT value FROM system_settings "
                "WHERE key = 'audit.retention_days'"
            )
        ).scalar()
    assert len(markers) == len(user_ids)
    # Raw SQL reads the stored form (SQLite keeps UUIDs as hex
    # text) — compare canonicalized.
    assert {uuid.UUID(str(m[0])) for m in markers} == set(user_ids)
    assert all(m[1] == "baseline" and m[2] == 0 for m in markers)
    assert setting == 180

    _run(engine, migration.downgrade)
    inspector = sa.inspect(engine)
    assert "change_journal" not in inspector.get_table_names()
    assert "restore_markers" not in inspector.get_table_names()
    assert "retained_files" not in inspector.get_table_names()
    with engine.connect() as conn:
        assert conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM system_settings "
                "WHERE key = 'audit.retention_days'"
            )
        ).scalar() == 0


def test_upgrade_never_stomps_an_existing_retention_value():
    migration = _load_migration()
    engine, _ = _pre_db(with_setting=45, user_count=1)
    _run(engine, migration.upgrade)
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT value FROM system_settings "
                "WHERE key = 'audit.retention_days'"
            )
        ).all()
    assert rows == [(45,)]
