"""Forum favorites (widget options Wave 3, owner design
2026-11-02, Decision 2): the forum_favorites table — one row
per (member, starred conversation). A favorite points at a
forum thread (kind "thread") or a permanent board's feedback
post (kind "post"); target_id is a plain polymorphic column
with no FK, so a favorite survives its target's deletion (the
read simply stops resolving it). Favorites are private: no
existing rows are touched and nothing is backfilled — every
member starts with an empty list, exactly like a layout with
no settings.

Revision ID: 0072_forum_favorites
Revises: 0071_rail_pinned
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0072_forum_favorites"
down_revision = "0071_rail_pinned"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forum_favorites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id",
            "kind",
            "target_id",
            name="uq_forum_favorite_user_target",
        ),
    )
    op.create_index(
        "ix_forum_favorites_user_id", "forum_favorites", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_forum_favorites_user_id", table_name="forum_favorites")
    op.drop_table("forum_favorites")
