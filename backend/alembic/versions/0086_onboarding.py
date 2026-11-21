"""0086: the onboarding wizard system (owner design 2026-10-31,
built 2026-11-07) — one new table, with its definition
WRITTEN INTO this script (row 116 fix, 2026-11-18 — the
original created it straight off the owning module's live
model; a migration carries the shape as of its own point in
the chain):

- onboarding_progress (core) — one row per (account, setup step):
  the guided pass's progress (done | skipped | notified), the
  "__fresh__" marker every post-wizard account is born with, the
  "__baseline__" module snapshot the new-feature detection reads,
  and the "__dismissed__" waiver row. It stores NO settings — the
  wizard writes through the same machinery Settings uses.

user_id is a plain id, not a foreign key (the 0038 lesson), so
this migration references no other table.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0086_onboarding"
down_revision = "0085_admin_lane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding_progress",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("step_key", sa.String(120), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="done"
        ),
        sa.Column(
            "detail", sa.Text(), nullable=False, server_default=""
        ),
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
        sa.UniqueConstraint(
            "user_id", "step_key", name="uq_onboarding_user_step"
        ),
    )
    op.create_index(
        "ix_onboarding_progress_user_id",
        "onboarding_progress",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("onboarding_progress")
