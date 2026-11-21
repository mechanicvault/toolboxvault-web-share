"""0085: the admin lane (owner program, 2026-11-06 23:14 +
23:45) — two tables, with their definitions WRITTEN INTO
this script (row 116 fix, 2026-11-18 — the original created
them straight off the owning modules' live models; a
migration carries the shape as of its own point in the
chain):

- site_stats_snapshots (core) — one row per day of site state
  (users by tier, free vs paying, MRR) that the admin Site
  Stats widget's day-over-day deltas read. Timestamps can't
  reconstruct what tier or plan a day ended in, so the jobs
  service snapshots it daily.

- community_blocks (forum) — one member's block from ONE
  community feature (forums | feedback_boards |
  community_parts), imposed/lifted by god + moderator_admin
  seats only. Per-feature and surgical — NOT the platform ban:
  the account, its inventory and every other feature stay
  untouched. Lifted, never deleted; one ACTIVE block per
  (member, feature) by partial unique index.

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0085_admin_lane"
down_revision = "0084_boards_urgency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_stats_snapshots",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
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
        "ix_site_stats_snapshots_day",
        "site_stats_snapshots",
        ["day"],
        unique=True,
    )
    op.create_table(
        "community_blocks",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("feature", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("blocked_by_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("lifted_by_id", PG_UUID(as_uuid=True)),
        sa.Column("lifted_at", sa.DateTime(timezone=True)),
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
        "ix_community_blocks_user_id", "community_blocks", ["user_id"]
    )
    op.create_index(
        "ix_community_blocks_feature", "community_blocks", ["feature"]
    )
    op.create_index(
        "uq_community_block_active",
        "community_blocks",
        ["user_id", "feature"],
        unique=True,
        postgresql_where=sa.text("lifted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("community_blocks")
    op.drop_table("site_stats_snapshots")
