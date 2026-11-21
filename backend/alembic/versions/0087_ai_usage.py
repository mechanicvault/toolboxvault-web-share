"""0087: the admin polish lane (owner corrections, 2026-11-07)
— one new table, with its definition WRITTEN INTO this
script (row 116 fix, 2026-11-18 — the original created it
straight off the owning module's live model; a migration
carries the shape as of its own point in the chain):

- ai_usage (billing) — one row per METERED AI action: when it
  ran, which action consumed it, what it was for (the consumer's
  subject), provider + model, provider call count, token counts,
  and the wallet credits charged. The wallet ledger records
  spends only, so at the default price of 0 an AI call left no
  trace and token counts were discarded by the transports; the
  admin AI Usage report reads THIS table. History starts with
  this migration — no earlier usage was ever recorded.

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0087_ai_usage"
down_revision = "0086_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column(
            "subject", sa.String(300), nullable=False, server_default=""
        ),
        sa.Column(
            "provider", sa.String(20), nullable=False, server_default=""
        ),
        sa.Column(
            "model", sa.String(100), nullable=False, server_default=""
        ),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("credits_charged", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ai_usage_user_id", "ai_usage", ["user_id"])
    op.create_index("ix_ai_usage_created_at", "ai_usage", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_usage")
