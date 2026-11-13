"""Wave 2 (2026-10-20): wishlist, sold tracking, truck accounts.

Three features, one migration:

- wishlist_items — the Wishlist module's one table (owner-scoped;
  dealer tag + converted-tool link are SET NULL references like
  the rest of the platform's cross-module tags).
- sale_records — inventory's SOLD ledger. item_id / set_id /
  reverses_id are PLAIN columns (no FK — the borrowing-ledger
  pattern: the record outlives the item, carrying its name
  snapshot; a reversal names the sale it compensates).
- truck_accounts + truck_entries — the Truck Accounts module.
  dealer_user_id / customer_user_id / recorded_by are PLAIN
  columns, deliberately (the 0038 warranty lesson: a two-party
  table whose user columns are FKs BLOCKS account deletion on
  Postgres; the core cascade tombstones these rows instead).
  truck_entries.account_id IS a real FK (CASCADE): entries are
  children of their account and never outlive it.
- dealer_agent_profiles gains the Stripe Connect seam columns
  (stripe_connect_account_id + charges/payouts flags +
  onboarding state) — written only by the (dark) Connect flow;
  they exist now so activation needs no migration.

Revision ID: 0040_wave2
Revises: 0039_asset_replaced
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_wave2"
down_revision: str | None = "0039_asset_replaced"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")
_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "wishlist_items",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("owner_id", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("link_url", sa.String(1000), nullable=False, server_default=""),
        sa.Column("target_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("priority", sa.String(10), nullable=False, server_default="normal"),
        sa.Column(
            "dealer_company_id",
            _UUID,
            sa.ForeignKey("dealer_companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachments", _JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="wanted"),
        sa.Column("purchased_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("purchased_on", sa.Date(), nullable=True),
        sa.Column(
            "converted_tool_id",
            _UUID,
            sa.ForeignKey("tools.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_wishlist_items_owner_id", "wishlist_items", ["owner_id"])

    op.create_table(
        "sale_records",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("owner_id", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_kind", sa.String(10), nullable=False),
        sa.Column("item_id", _UUID, nullable=False),
        sa.Column("set_id", _UUID, nullable=True),
        sa.Column("item_name", sa.String(300), nullable=False, server_default=""),
        sa.Column("quantity_sold", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("buyer_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("buyer_contact", sa.String(300), nullable=False, server_default=""),
        sa.Column("sale_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("sold_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("kind", sa.String(20), nullable=False, server_default="sale"),
        sa.Column("reverses_id", _UUID, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        # Monotonic insertion order (borrowing seq precedent): the
        # app's before_insert hook draws from sale_records_seq on
        # Postgres, max+1 on SQLite. Nullable in the migration —
        # the table is new and empty; the model carries it too.
        sa.Column("seq", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_sale_records_owner_id", "sale_records", ["owner_id"])
    op.create_index("ix_sale_records_item_id", "sale_records", ["item_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE SEQUENCE IF NOT EXISTS sale_records_seq")

    op.create_table(
        "truck_accounts",
        sa.Column("id", _UUID, primary_key=True),
        # PLAIN columns on purpose — see the module docstring.
        sa.Column("dealer_user_id", _UUID, nullable=False),
        sa.Column("customer_user_id", _UUID, nullable=True),
        sa.Column("customer_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("customer_name", sa.String(300), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="invited"),
        sa.Column("invite_token", sa.String(64), nullable=False),
        sa.Column("agreement_version", sa.String(20), nullable=True),
        sa.Column("agreement_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agreement_text_snapshot", sa.Text(), nullable=True),
        sa.Column(
            "payment_cadence", sa.String(20), nullable=False, server_default="weekly"
        ),
        sa.Column("payment_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column(
            "customer_deleted", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "dealer_deleted", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_truck_accounts_dealer_user_id", "truck_accounts", ["dealer_user_id"])
    op.create_index("ix_truck_accounts_customer_user_id", "truck_accounts", ["customer_user_id"])
    op.create_index(
        "ix_truck_accounts_invite_token", "truck_accounts", ["invite_token"], unique=True
    )

    op.create_table(
        "truck_entries",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "account_id",
            _UUID,
            sa.ForeignKey("truck_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Denormalized from the account so the change journal can
        # attribute entries to the dealer without a join.
        sa.Column("dealer_user_id", _UUID, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        # SIGNED: charges positive, payments negative, adjustments
        # as entered. Balance = SUM(amount), computed never stored.
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("item_link_id", _UUID, nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("recorded_by", _UUID, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_truck_entries_account_id", "truck_entries", ["account_id"])

    op.add_column(
        "dealer_agent_profiles",
        sa.Column("stripe_connect_account_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column(
            "connect_charges_enabled", sa.Boolean(),
            nullable=False, server_default="false",
        ),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column(
            "connect_payouts_enabled", sa.Boolean(),
            nullable=False, server_default="false",
        ),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column(
            "connect_onboarding_state", sa.String(30),
            nullable=False, server_default="not_started",
        ),
    )


def downgrade() -> None:
    op.drop_column("dealer_agent_profiles", "connect_onboarding_state")
    op.drop_column("dealer_agent_profiles", "connect_payouts_enabled")
    op.drop_column("dealer_agent_profiles", "connect_charges_enabled")
    op.drop_column("dealer_agent_profiles", "stripe_connect_account_id")
    op.drop_table("truck_entries")
    op.drop_table("truck_accounts")
    op.drop_table("sale_records")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP SEQUENCE IF EXISTS sale_records_seq")
    op.drop_table("wishlist_items")
