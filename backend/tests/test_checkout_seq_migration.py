"""Migration 0023 (checkout seq — hardening 2026-10-19).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0023 checkouts table and pins:

- every existing row is backfilled, numbered in (created_at, id)
  order starting at 1 — including rows that share one created_at
  tick (the exact shape that raced);
- seq ends NOT NULL;
- downgrade removes the column.
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
    / "0023_checkout_seq.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0023_checkout_seq", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0023_engine():
    """A checkouts table as of 0022: the columns 0023 reads (id,
    created_at) and nothing of seq. Three rows share one tick."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE checkouts ("
                " id VARCHAR(36) PRIMARY KEY,"
                " created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO checkouts (id, created_at) VALUES"
                " ('bbbb', '2026-10-18 10:00:00'),"
                " ('aaaa', '2026-10-18 10:00:00'),"
                " ('cccc', '2026-10-18 10:00:00'),"
                " ('dddd', '2026-10-17 09:00:00')"
            )
        )
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_upgrade_backfills_seq_in_created_then_id_order():
    migration = _load_migration()
    engine = _pre_0023_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        rows = conn.execute(
            sa.text("SELECT id, seq FROM checkouts ORDER BY seq")
        ).all()
        # dddd is a day older -> 1. The three same-tick rows follow
        # in id order: aaaa, bbbb, cccc.
        assert [(r.id, r.seq) for r in rows] == [
            ("dddd", 1),
            ("aaaa", 2),
            ("bbbb", 3),
            ("cccc", 4),
        ]
        # seq is NOT NULL after the upgrade: a raw insert without
        # it must fail.
        import pytest

        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as nested:
                nested.execute(
                    sa.text(
                        "INSERT INTO checkouts (id, created_at)"
                        " VALUES ('eeee', '2026-10-19 00:00:00')"
                    )
                )


def test_downgrade_removes_seq():
    migration = _load_migration()
    engine = _pre_0023_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
        cols = {
            row[1]
            for row in conn.execute(sa.text("PRAGMA table_info(checkouts)"))
        }
        assert cols == {"id", "created_at"}
