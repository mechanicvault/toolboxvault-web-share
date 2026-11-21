"""0088: the cancellation counts lane (owner 2026-11-07) —
one new table, with its definition WRITTEN INTO this
script (row 116 fix, 2026-11-18 — the original created it
straight off the owning module's live model; a migration
carries the shape as of its own point in the chain):

- subscription_status_changes (billing) — one row per RECORDED
  subscription status transition: the subscription, the status
  it left, the status it entered, when, and the change's
  source. The Subscription row stores only its current status,
  so before this lane no cancellation date existed anywhere
  and the admin Accounting report printed that gap instead of
  a count. Writers append transitions only (a same-status
  re-save records nothing); the report counts a cancellation
  as a live state (active | trialing | past_due) reaching a
  terminal state (canceled | ended), once. History starts
  with this migration — no earlier change was ever recorded,
  and no row pretends otherwise.

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0088_subscription_status_changes"
down_revision = "0087_ai_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_status_changes",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subscription_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column(
            "source", sa.String(32), nullable=False, server_default=""
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_subscription_status_changes_subscription_id",
        "subscription_status_changes",
        ["subscription_id"],
    )
    op.create_index(
        "ix_subscription_status_changes_user_id",
        "subscription_status_changes",
        ["user_id"],
    )
    op.create_index(
        "ix_subscription_status_changes_created_at",
        "subscription_status_changes",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("subscription_status_changes")
