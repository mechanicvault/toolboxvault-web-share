"""Migration 0049 (acquisition ledger) upgrades a 0048-shaped
database cleanly: the table appears, priced tools/batteries are
backfilled one ledger row each from their current facts,
price-less items get NO row, and the downgrade removes exactly
what the upgrade added."""

import importlib.util
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
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
        / "0049_acquisition_ledger.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0049", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0049 shape: users (the ledger's FK target) and
    tools/batteries carrying exactly the columns the backfill
    reads."""
    meta = MetaData()
    Table(
        "users",
        meta,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("email", String(300), nullable=False),
    )
    def item_columns():
        return [
            Column("id", PG_UUID(as_uuid=True), primary_key=True),
            Column("owner_id", PG_UUID(as_uuid=True), nullable=False),
            Column("name", String(300), nullable=False),
            Column("brand", String(200), nullable=False),
            Column("business_use", Boolean, nullable=False),
            Column("purchase_date", Date),
            Column("purchase_price", Numeric(12, 2)),
            Column("quantity", Integer, nullable=False),
        ]

    Table("tools", meta, *item_columns())
    Table("batteries", meta, *item_columns())
    meta.create_all(engine)


def test_migration_0049_upgrade_backfill_and_downgrade():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = create_engine("sqlite://")
    _pre_state(engine)
    owner_id = uuid.uuid4()
    tool_id = uuid.uuid4()
    battery_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email) VALUES (:id, 'a@example.com')"
            ),
            {"id": str(owner_id)},
        )
        conn.execute(
            text(
                "INSERT INTO tools (id, owner_id, name, brand, business_use,"
                " purchase_date, purchase_price, quantity) VALUES"
                " (:id, :owner, 'Impact wrench', 'Milwaukee', 1,"
                " '2026-02-01', 149.00, 3)"
            ),
            {"id": str(tool_id), "owner": str(owner_id)},
        )
        # A price-less battery: no money recorded → no ledger row.
        conn.execute(
            text(
                "INSERT INTO batteries (id, owner_id, name, brand,"
                " business_use, purchase_date, purchase_price, quantity)"
                " VALUES (:id, :owner, 'M18 pack', 'Milwaukee', 0,"
                " '2026-05-05', NULL, 4)"
            ),
            {"id": str(battery_id), "owner": str(owner_id)},
        )

    module = _load_migration()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()
        assert "acquisition_records" in set(inspect(conn).get_table_names())
        rows = conn.execute(
            text(
                "SELECT item_kind, item_name, quantity_acquired,"
                " unit_price, acquired_on FROM acquisition_records"
            )
        ).all()
        assert len(rows) == 1
        kind, name, qty, price, when = rows[0]
        assert kind == "tool"
        assert name == "Impact wrench"
        assert qty == 3
        assert Decimal(str(price)) == Decimal("149.00")
        assert str(when)[:10] == "2026-02-01"

        with Operations.context(ctx):
            module.downgrade()
        assert "acquisition_records" not in set(
            inspect(conn).get_table_names()
        )
