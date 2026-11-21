"""Migration 0033 (Tools For Sale + reputation).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0033 database (users only — the one table the new
tables reference) and pins:

- the four new tables land (sale_listings, deal_interactions,
  ratings, thread_completions);
- the honesty constraints land with them: one interaction per
  deal (dedupe_key unique), one rating per side per interaction
  (unique pair), stars bounded 1–5 (check);
- downgrade removes everything it added.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0033_marketplace.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0033", _MIGRATION_PATH)
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


def test_upgrade_creates_tables_and_constraints():
    engine = _pre_db()
    migration = _load_migration()
    _run(engine, migration.upgrade)

    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "sale_listings",
        "deal_interactions",
        "ratings",
        "thread_completions",
    } <= tables

    listing_cols = {c["name"] for c in inspector.get_columns("sale_listings")}
    assert {
        "owner_id",
        "listing_type",
        "title",
        "price",
        "status",
        "buyer_id",
        "source_kind",
        "attachments",
    } <= listing_cols

    unique_sets = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("deal_interactions")
    }
    assert ("dedupe_key",) in unique_sets
    rating_uniques = {
        tuple(sorted(uc["column_names"]))
        for uc in inspector.get_unique_constraints("ratings")
    }
    assert ("interaction_id", "rater_id") in rating_uniques
    checks = {
        cc["name"] for cc in inspector.get_check_constraints("ratings")
    }
    assert "ck_ratings_stars" in checks

    # The constraints bite: a second rating from the same side of
    # the same deal is refused by the database itself.
    with engine.connect() as conn:
        low, high = uuid.uuid4(), uuid.uuid4()
        interaction_id = uuid.uuid4()
        # Timestamps are supplied explicitly: the created_at
        # server default is Postgres now(), which SQLite lacks —
        # the same reason the ORM models carry their own defaults
        # in the app runtime.
        stamp = "2026-10-19 00:00:00+00:00"
        conn.execute(
            sa.text(
                "INSERT INTO deal_interactions (id, party_low_id, party_high_id,"
                " dedupe_key, completed_at, created_at)"
                " VALUES (:id, :low, :high, 'listing:x', :ts, :ts)"
            ),
            {"id": interaction_id.hex, "low": low.hex, "high": high.hex, "ts": stamp},
        )
        conn.execute(
            sa.text(
                "INSERT INTO ratings (id, interaction_id, rater_id, ratee_id,"
                " stars, created_at) VALUES (:id, :iid, :rater, :ratee, 5, :ts)"
            ),
            {
                "id": uuid.uuid4().hex,
                "iid": interaction_id.hex,
                "rater": low.hex,
                "ratee": high.hex,
                "ts": stamp,
            },
        )
        conn.commit()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO ratings (id, interaction_id, rater_id,"
                    " ratee_id, stars, created_at)"
                    " VALUES (:id, :iid, :rater, :ratee, 1, :ts)"
                ),
                {
                    "id": uuid.uuid4().hex,
                    "iid": interaction_id.hex,
                    "rater": low.hex,
                    "ratee": high.hex,
                    "ts": stamp,
                },
            )
            conn.commit()


def test_downgrade_removes_everything():
    engine = _pre_db()
    migration = _load_migration()
    _run(engine, migration.upgrade)
    _run(engine, migration.downgrade)
    tables = set(sa.inspect(engine).get_table_names())
    assert not {
        "sale_listings",
        "deal_interactions",
        "ratings",
        "thread_completions",
    } & tables
