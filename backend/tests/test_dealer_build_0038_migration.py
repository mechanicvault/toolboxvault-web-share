"""Migration 0038: drop the requester FK 0037 shipped with.

Builds the table AS 0037 ORIGINALLY created it (with the FK),
runs 0038, and pins: the FK is gone, the column stays.
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
    / "0038_warranty_requester_fk.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0038", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine_with_fk():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    meta = sa.MetaData()
    sa.Table("users", meta, sa.Column("id", sa.Uuid, primary_key=True))
    sa.Table(
        "warranty_service_requests", meta,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("requester_id", sa.Uuid, nullable=False),
        # Named exactly as Postgres auto-named it when 0037 ran
        # live — that is the constraint this migration removes.
        sa.ForeignKeyConstraint(
            ["requester_id"], ["users.id"],
            name="warranty_service_requests_requester_id_fkey",
        ),
    )
    meta.create_all(engine)
    return engine


def _run(engine, fn):
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            fn()
        conn.commit()


def _requester_fks(engine):
    inspector = sa.inspect(engine)
    return [
        fk for fk in inspector.get_foreign_keys("warranty_service_requests")
        if fk.get("constrained_columns") == ["requester_id"]
    ]


def test_upgrade_drops_only_the_requester_fk():
    module = _load_migration()
    assert module.down_revision == "0037_dealer_build"
    engine = _engine_with_fk()
    assert len(_requester_fks(engine)) == 1
    _run(engine, module.upgrade)
    assert _requester_fks(engine) == []
    columns = {
        c["name"]
        for c in sa.inspect(engine).get_columns("warranty_service_requests")
    }
    assert columns == {"id", "requester_id"}
