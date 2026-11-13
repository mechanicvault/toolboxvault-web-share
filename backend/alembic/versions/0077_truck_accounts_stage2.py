"""Truck accounts stage 2 (owner model, 2026-11-04; build,
2026-11-05): the mechanic's seat — self-kept accounts, payment
requests, missed-payment state.

- truck_accounts gains WHO KEEPS THE LEDGER
  (ledger_keeper: "agent" | "customer", default "agent" — every
  existing row keeps exactly the behavior it has today) and
  the customer's pay-through-the-site choice (payment_mode:
  "manual" | "automatic", default "manual"; stored state only,
  Stripe Connect stays dark).
- New table truck_payment_requests: an agent's payment ask on
  a customer-kept shared account, the customer's decision, and
  the ledger entry approval wrote. account_id is a real FK
  (CASCADE — a request is meaningless without its account, the
  truck_entries posture); the user columns are PLAIN (the
  module's two-party posture: rows survive a party's deletion).

All DDL goes through SQLAlchemy ops (no hand-written SQL);
every existing column name was verified against `\\d
truck_accounts` / `\\d truck_entries` on production and the
0068 creating migration before this was written.

Revision ID: 0077_truck_accounts_stage2
Revises: 0076_claims_separation
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0077_truck_accounts_stage2"
down_revision = "0076_claims_separation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "truck_accounts",
        sa.Column(
            "ledger_keeper",
            sa.String(length=12),
            nullable=False,
            server_default="agent",
        ),
    )
    op.add_column(
        "truck_accounts",
        sa.Column(
            "payment_mode",
            sa.String(length=10),
            nullable=False,
            server_default="manual",
        ),
    )
    op.create_table(
        "truck_payment_requests",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by", UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("entry_id", UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by", UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decision_note", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["truck_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_truck_payment_requests_account_id",
        "truck_payment_requests",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_truck_payment_requests_account_id",
        table_name="truck_payment_requests",
    )
    op.drop_table("truck_payment_requests")
    op.drop_column("truck_accounts", "payment_mode")
    op.drop_column("truck_accounts", "ledger_keeper")
