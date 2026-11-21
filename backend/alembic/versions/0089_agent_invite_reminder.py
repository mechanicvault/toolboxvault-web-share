"""0089: the 30-day agent invite reminder (owner order,
2026-11-07) — one new column on private_agents:

- invite_reminded_at — the stamp the daily agent-invite sweep
  writes in the same commit as the ONE inbox reminder a
  still-unclaimed private agent record earns at 30 days old
  ("invite your agent to join the network"). NULL = never
  reminded; the stamp on the record itself is the once-ever
  dedupe (the claims backorder_last_reminded_at pattern), so it
  survives scheduler restarts and repeat sweeps, an owner
  deleting the inbox note cannot resurrect a second reminder,
  and a record deleted before day 30 takes its marker with it.

Plain column add, nullable, no server default, no model
__table__ DDL and no hand-written SQL — the 0084 posture:
nothing here can drift from a column name or strand an FK in
a bare process. Existing rows land NULL (never reminded),
which is simply true: no reminder existed before this.
"""

import sqlalchemy as sa
from alembic import op

revision = "0089_agent_invite_reminder"
down_revision = "0088_subscription_status_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "private_agents",
        sa.Column(
            "invite_reminded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("private_agents", "invite_reminded_at")
