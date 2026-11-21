"""Rate limiter events — shared limiter counts (sheet row 115).

The login limiter (and its sibling doors) counted failed
attempts in process memory, but the API runs two uvicorn
workers: every budget was effectively doubled and a lockout
depended on which worker a request landed on. The counters
move into the database — one row per counted attempt, keyed
by the limiter key, timestamped in wall-clock epoch seconds
(monotonic clocks are per-process). Rows older than a
limiter's window are pruned on the next write for that key,
so the table tracks live traffic, not history.

The table is brand new; there is nothing to verify against
the live schema beyond its absence (checked 2026-11-18).

Revision ID: 0110_rate_limit_events
Revises: 0109_print_file_slug
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0110_rate_limit_events"
down_revision = "0109_print_file_slug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("ts", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rate_limit_events_key_ts",
        "rate_limit_events",
        ["key", "ts"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_events_key_ts", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
