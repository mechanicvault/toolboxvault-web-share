"""Migration 0037 (dealer build, 2026-10-20).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0037 database and pins:

- dealer_agent_profiles gains the six service-area columns;
- geocode_cache + warranty_service_requests land with their
  columns;
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
    / "0037_dealer_build.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0037", _MIGRATION_PATH)
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
    )
    sa.Table(
        "dealer_companies", meta, sa.Column("id", sa.Uuid, primary_key=True),
    )
    sa.Table(
        "dealer_agent_profiles", meta,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("user_id", sa.Uuid),
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
    assert module.down_revision == "0036_gap_wave1"
    engine = _pre_db()
    _run(engine, module.upgrade)

    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"geocode_cache", "warranty_service_requests"} <= tables

    profile_columns = _columns(inspector, "dealer_agent_profiles")
    assert {
        "area_type", "area_polygon", "area_center_lat",
        "area_center_lng", "area_radius_km", "area_zip",
    } <= profile_columns

    assert _columns(inspector, "geocode_cache") == {
        "id", "query_key", "query_text", "lat", "lng",
        "display_name", "source", "created_at",
    }
    assert _columns(inspector, "warranty_service_requests") == {
        "id", "requester_id", "company_id", "company_name",
        "repair_record_id", "item_kind", "item_id", "item_name",
        "brand", "model", "serials", "problem", "purchase_date",
        "warranty_status", "requester_name", "requester_email",
        "requester_phone", "requester_area", "routed_agent_ids",
        "claimed_by_id", "status", "requester_deleted",
        "resolved_at", "created_at", "updated_at",
    }

    _run(engine, module.downgrade)
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert "geocode_cache" not in tables
    assert "warranty_service_requests" not in tables
    assert _columns(inspector, "dealer_agent_profiles") == {"id", "user_id"}
