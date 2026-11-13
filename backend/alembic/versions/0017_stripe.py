"""Stripe wiring (billing, 2026-10-19): customer ids, subscription
mirror facts, and the webhook idempotency ledger.

Ships completely DARK — the owner's Stripe account doesn't exist
yet (it will be created under MechanicVault@gmail.com), no keys are
configured anywhere, and every payment surface answers "not
configured" until they are. This migration only prepares the
schema:

- users.stripe_customer_id — created lazily at first checkout;
  the join key webhooks resolve users by. UNIQUE (one customer
  per account; Postgres/SQLite both allow many NULLs).
- subscriptions.stripe_subscription_id / stripe_status — the
  provider's raw facts next to our normalized status, so the row
  reconciles against the Stripe dashboard at a glance.
- subscriptions.bracket_key — the Business bracket declared at
  checkout (base + bracket is the price structure; employee
  counting doesn't exist yet, so the declaration is stored).
- stripe_events — one row per accepted webhook event id; the
  idempotency ledger that makes Stripe's retries harmless.

Revision ID: 0017_stripe
Revises: 0016_item_structure
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_stripe"
down_revision: str | None = "0016_item_structure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("stripe_customer_id", sa.String(64), nullable=True)
    )
    # A unique INDEX (not a constraint): same one-customer-per-
    # account guarantee, and portable across Postgres and SQLite.
    op.create_index(
        "uq_users_stripe_customer_id",
        "users",
        ["stripe_customer_id"],
        unique=True,
    )
    op.add_column(
        "subscriptions",
        sa.Column("stripe_subscription_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("stripe_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("bracket_key", sa.String(32), nullable=True),
    )
    op.create_table(
        "stripe_events",
        sa.Column("event_id", sa.String(200), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False, server_default=""),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_table("stripe_events")
    op.drop_column("subscriptions", "bracket_key")
    op.drop_column("subscriptions", "stripe_status")
    op.drop_column("subscriptions", "stripe_subscription_id")
    op.drop_index("uq_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "stripe_customer_id")
