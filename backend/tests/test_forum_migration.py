"""Migration 0034 (Community Forum).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0034 database (users only — the one table the new
tables reference) and pins:

- the four new tables land (forum_categories, forum_threads,
  forum_posts, forum_reports);
- the starter category set seeds with the mechanic-first rooms,
  in order, all active;
- the no-FK doctrine on author ids (threads/posts survive
  deletion as tombstones) while reports keep their reporter FK;
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
    / "0034_forum.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0034", _MIGRATION_PATH)
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
    sa.Table(
        "users",
        meta,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("email", sa.String(320)),
    )
    meta.create_all(engine)
    return engine


def _run(engine, fn):
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            fn()
        conn.commit()


def test_upgrade_creates_tables_and_seeds_categories():
    module = _load_migration()
    engine = _pre_db()
    _run(engine, module.upgrade)

    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "forum_categories",
        "forum_threads",
        "forum_posts",
        "forum_reports",
    } <= tables

    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT name, sort_order, is_active FROM forum_categories "
                "ORDER BY sort_order"
            )
        ).all()
    assert [row[0] for row in rows] == [
        "General Discussion",
        "Tool Talk",
        "Repair Help",
        "Deals & Finds",
        "Shop Talk",
    ]
    assert all(row[2] for row in rows)

    # The tombstone doctrine: no FK from posts/threads to users;
    # reports DO reference their reporter.
    post_fks = inspector.get_foreign_keys("forum_posts")
    assert all(fk["referred_table"] != "users" for fk in post_fks)
    thread_fks = inspector.get_foreign_keys("forum_threads")
    assert all(fk["referred_table"] != "users" for fk in thread_fks)
    report_fks = inspector.get_foreign_keys("forum_reports")
    assert any(fk["referred_table"] == "users" for fk in report_fks)


def test_downgrade_removes_everything():
    module = _load_migration()
    engine = _pre_db()
    _run(engine, module.upgrade)
    _run(engine, module.downgrade)
    tables = set(sa.inspect(engine).get_table_names())
    assert "forum_categories" not in tables
    assert "forum_threads" not in tables
    assert "forum_posts" not in tables
    assert "forum_reports" not in tables
    assert "users" in tables  # the pre-existing table survives
    _ = uuid  # (kept import parity with the sibling migration tests)
