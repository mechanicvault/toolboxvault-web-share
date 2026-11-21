"""Migration 0039 (asset history — replaced marker) upgrades a
0038-shaped database cleanly: tools + batteries gain
replaced_on / replaced_by_item_id / replaced_note, existing
rows read back NULL/empty (never replaced), and the downgrade
removes exactly what the upgrade added. The replaced_by id is
a PLAIN column — no foreign key (the ledger pattern: the marker
must survive the replacement record's deletion).
"""

import importlib.util
from pathlib import Path

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0039_asset_replaced.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0039", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0039 shape: the two tables with the columns
    the migration touches around."""
    meta = MetaData()
    for name in ("tools", "batteries"):
        Table(
            name,
            meta,
            Column("id", PG_UUID(as_uuid=True), primary_key=True),
            Column("owner_id", PG_UUID(as_uuid=True), nullable=False),
            Column("name", String(300), nullable=False),
            Column("created_at", DateTime(timezone=True)),
        )
    meta.create_all(engine)


def test_migration_0039_upgrade_and_downgrade():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = create_engine("sqlite://")
    _pre_state(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tools (id, owner_id, name) VALUES "
                "('11111111-1111-1111-1111-111111111111', "
                "'22222222-2222-2222-2222-222222222222', 'Old wrench')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO batteries (id, owner_id, name) VALUES "
                "('33333333-3333-3333-3333-333333333333', "
                "'22222222-2222-2222-2222-222222222222', 'Old pack')"
            )
        )

    migration = _load_migration()
    assert migration.revision == "0039_asset_replaced"
    assert migration.down_revision == "0038_warranty_requester_fk"

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()

    inspector = inspect(engine)
    for table in ("tools", "batteries"):
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        assert "replaced_on" in columns
        assert isinstance(columns["replaced_on"]["type"], Date)
        assert "replaced_by_item_id" in columns
        assert "replaced_note" in columns
        # The doctrine pin: NO foreign key on the marker.
        assert inspector.get_foreign_keys(table) == []

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT replaced_on, replaced_by_item_id, replaced_note "
                "FROM tools"
            )
        ).one()
        assert row == (None, None, "")
        row = conn.execute(
            text("SELECT replaced_note FROM batteries")
        ).one()
        assert row == ("",)

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.downgrade()
    inspector = inspect(engine)
    for table in ("tools", "batteries"):
        names = {c["name"] for c in inspector.get_columns(table)}
        assert "replaced_on" not in names
        assert "replaced_by_item_id" not in names
        assert "replaced_note" not in names
        _ = Text  # (import parity with other migration tests)
