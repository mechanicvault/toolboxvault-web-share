"""Acquisition ledger (year-end fix, 2026-10-24).

WHY: the year-end report's Acquired section (and the tax
worksheet's purchase sections) computed acquisitions from each
item's CURRENT quantity — purchase_price × quantity — so a
partial sale rewrote purchase history (bought 3 × $149, sold 1
→ the report claimed Acquired 2 / $298). The fix is a permanent
acquisition ledger, inventory-owned, written by the inventory
service at item creation and on quantity increases; sales,
reversals, decreases and deletion never shrink it.

- acquisition_records — one row per acquisition event. item_id
  is a PLAIN column (no FK — the sold-ledger pattern: the record
  outlives the item, carrying name/brand/business-use snapshots);
  owner_id IS a user FK like every other owner-scoped ledger,
  and core's account-deletion cascade sweeps by owner_id.
- BACKFILL: one row per existing tool/battery that carries a
  purchase price, from its current quantity + purchase_date +
  purchase_price (best available truth). Price-less items get
  no row — a price-less acquisition records no money, and the
  reports' fallback read covers them exactly as before.
  Portions already sold before this migration cannot be
  reconstructed from current quantities and are NOT invented;
  production holds no migrated user data yet, and the future
  Emergent migration writes ledger rows at import from the
  app's original quantities.

Revision ID: 0049_acquisition_ledger
Revises: 0048_user_locale
Create Date: 2026-10-24
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049_acquisition_ledger"
down_revision: str | None = "0048_user_locale"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "acquisition_records",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "owner_id", _UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("item_kind", sa.String(10), nullable=False),
        sa.Column("item_id", _UUID, nullable=False),
        sa.Column("item_name", sa.String(300), nullable=False, server_default=""),
        sa.Column("brand", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "business_use",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("acquired_on", sa.Date(), nullable=True),
        sa.Column("quantity_acquired", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_acquisition_records_owner_id", "acquisition_records", ["owner_id"]
    )
    op.create_index(
        "ix_acquisition_records_item_id", "acquisition_records", ["item_id"]
    )

    # -- backfill: one row per priced tool/battery ----------------
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    items = sa.table(
        "tools",
        sa.Column("id", sa.Uuid()),
        sa.Column("owner_id", sa.Uuid()),
        sa.Column("name", sa.String()),
        sa.Column("brand", sa.String()),
        sa.Column("business_use", sa.Boolean()),
        sa.Column("purchase_date", sa.Date()),
        sa.Column("purchase_price", sa.Numeric(12, 2)),
        sa.Column("quantity", sa.Integer()),
    )
    batteries = sa.table(
        "batteries",
        sa.Column("id", sa.Uuid()),
        sa.Column("owner_id", sa.Uuid()),
        sa.Column("name", sa.String()),
        sa.Column("brand", sa.String()),
        sa.Column("business_use", sa.Boolean()),
        sa.Column("purchase_date", sa.Date()),
        sa.Column("purchase_price", sa.Numeric(12, 2)),
        sa.Column("quantity", sa.Integer()),
    )
    ledger = sa.table(
        "acquisition_records",
        sa.Column("id", sa.Uuid()),
        sa.Column("owner_id", sa.Uuid()),
        sa.Column("item_kind", sa.String(10)),
        sa.Column("item_id", sa.Uuid()),
        sa.Column("item_name", sa.String(300)),
        sa.Column("brand", sa.String(200)),
        sa.Column("business_use", sa.Boolean()),
        sa.Column("acquired_on", sa.Date()),
        sa.Column("quantity_acquired", sa.Integer()),
        sa.Column("unit_price", sa.Numeric(12, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    rows: list[dict] = []
    for source, kind in ((items, "tool"), (batteries, "battery")):
        for item in bind.execute(
            sa.select(source).where(source.c.purchase_price.is_not(None))
        ).mappings():
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "owner_id": item["owner_id"],
                    "item_kind": kind,
                    "item_id": item["id"],
                    "item_name": item["name"] or "",
                    "brand": item["brand"] or "",
                    "business_use": bool(item["business_use"]),
                    "acquired_on": item["purchase_date"],
                    "quantity_acquired": item["quantity"] or 1,
                    "unit_price": item["purchase_price"],
                    "created_at": now,
                    "updated_at": now,
                }
            )
    if rows:
        op.bulk_insert(ledger, rows)


def downgrade() -> None:
    op.drop_index("ix_acquisition_records_item_id", table_name="acquisition_records")
    op.drop_index("ix_acquisition_records_owner_id", table_name="acquisition_records")
    op.drop_table("acquisition_records")
