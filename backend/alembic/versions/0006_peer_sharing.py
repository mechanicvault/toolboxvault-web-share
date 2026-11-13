"""Add peer_shares + peer_share_exclusions (peer sharing).

Owner directive 2026-10-17: a person shares their tool LIST with
specific other people — mechanics sharing with their crew so anyone
can search "who has this tool?", a shop owner sharing shop tools
the same way. Two tables:

  - peer_shares: one grant per (owner, viewer). The viewer is named
    by account (viewer_user_id) and/or by invited_email — an email
    invite to someone without an account waits as pending-by-email
    and attaches when that email signs up. Status pending →
    accepted; decline/revoke/leave delete the row.
  - peer_share_exclusions: tools the owner withholds from ALL peer
    viewers (peer sharing is default-include, the opposite shape
    from tier sharing's explicit item rows).

The peer payload itself is fixed and minimal (identity + photos)
and is built in app/modules/core/peer_sharing.py — no payload
columns live here.

Revision ID: 0006_peer_sharing
Revises: 0005_sharing
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_peer_sharing"
down_revision: str | Sequence[str] | None = "0005_sharing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "peer_shares",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("viewer_user_id", sa.UUID(), nullable=True),
        sa.Column("invited_email", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["viewer_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "viewer_user_id", name="uq_peer_share_owner_viewer"
        ),
    )
    op.create_index("ix_peer_shares_owner_id", "peer_shares", ["owner_id"])
    op.create_index(
        "ix_peer_shares_viewer_user_id", "peer_shares", ["viewer_user_id"]
    )
    op.create_table(
        "peer_share_exclusions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tool_id"], ["tools.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "tool_id", name="uq_peer_exclusion_owner_tool"
        ),
    )
    op.create_index(
        "ix_peer_share_exclusions_owner_id", "peer_share_exclusions", ["owner_id"]
    )
    op.create_index(
        "ix_peer_share_exclusions_tool_id", "peer_share_exclusions", ["tool_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_peer_share_exclusions_tool_id", table_name="peer_share_exclusions")
    op.drop_index("ix_peer_share_exclusions_owner_id", table_name="peer_share_exclusions")
    op.drop_table("peer_share_exclusions")
    op.drop_index("ix_peer_shares_viewer_user_id", table_name="peer_shares")
    op.drop_index("ix_peer_shares_owner_id", table_name="peer_shares")
    op.drop_table("peer_shares")
