"""Migration 0036 (gap-closer wave 1, 2026-10-20).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0036 database (the tables it touches: users,
ratings, tools, batteries, checkouts) and pins:

- ratings gains removed_at / removed_by_id; rating_reports lands
  with its columns and indexes;
- tools + batteries gain the four structured-warranty columns;
- inventory_categories lands with the (owner, normalized) unique;
- item_loss_reports lands with the one-active partial index;
- borrower_contacts lands; checkouts gains borrower_contact_id;
- downgrade removes everything it added.
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
    / "0036_gap_wave1.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0036", _MIGRATION_PATH)
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
        "users", meta, sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("email", sa.String(320)),
    )
    sa.Table(
        "ratings", meta, sa.Column("id", sa.Uuid, primary_key=True),
    )
    for table in ("tools", "batteries"):
        sa.Table(table, meta, sa.Column("id", sa.Uuid, primary_key=True))
    sa.Table(
        "checkouts", meta, sa.Column("id", sa.Uuid, primary_key=True),
    )
    meta.create_all(engine)
    return engine


def _run(engine, fn):
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            fn()
        conn.commit()


def _columns(inspector, table):
    return {c["name"] for c in inspector.get_columns(table)}


def test_upgrade_and_downgrade():
    module = _load_migration()
    assert module.down_revision == "0035_job_runs"
    engine = _pre_db()
    _run(engine, module.upgrade)

    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "rating_reports",
        "inventory_categories",
        "item_loss_reports",
        "borrower_contacts",
    } <= tables

    assert {"removed_at", "removed_by_id"} <= _columns(inspector, "ratings")
    assert _columns(inspector, "rating_reports") == {
        "id", "rating_id", "reporter_id", "reason", "status",
        "resolution", "resolved_by_id", "resolved_at", "created_at",
    }
    warranty = {
        "warranty_provider", "warranty_contact", "warranty_terms",
        "warranty_type",
    }
    for table in ("tools", "batteries"):
        assert warranty <= _columns(inspector, table)
    assert _columns(inspector, "inventory_categories") == {
        "id", "owner_id", "name", "normalized", "created_at", "updated_at",
    }
    uniques = {
        tuple(uc["column_names"])
        for uc in inspector.get_unique_constraints("inventory_categories")
    }
    assert ("owner_id", "normalized") in uniques
    assert _columns(inspector, "item_loss_reports") == {
        "id", "owner_id", "item_kind", "item_id", "status", "standing",
        "reported_date", "police_report_number", "police_department",
        "insurer_name", "claim_number", "notes", "recovered_date",
        "created_at", "updated_at",
    }
    loss_indexes = {
        ix["name"] for ix in inspector.get_indexes("item_loss_reports")
    }
    assert "uq_loss_reports_one_active_per_item" in loss_indexes
    assert _columns(inspector, "borrower_contacts") == {
        "id", "owner_id", "name", "contact", "notes", "linked_user_id",
        "created_at", "updated_at",
    }
    assert "borrower_contact_id" in _columns(inspector, "checkouts")

    _run(engine, module.downgrade)
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert not (
        {"rating_reports", "inventory_categories", "item_loss_reports",
         "borrower_contacts"}
        & tables
    )
    assert "removed_at" not in _columns(inspector, "ratings")
    assert "warranty_type" not in _columns(inspector, "tools")
    assert "borrower_contact_id" not in _columns(inspector, "checkouts")
