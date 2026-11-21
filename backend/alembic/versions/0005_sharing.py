"""Add share_configs + shared_items (consent sharing).

Owner directive 2026-10-17: a mechanic may share their tool list
with the shop group and/or the insurance group — only what they
approve. Two halves:

  - share_configs: per (owner, recipient group) — an enabled flag
    and the list of OPTIONAL fields the owner lets that group see.
    Locked identity fields (name/brand/model/serial_number) are not
    stored; they always accompany a shared item. No row = sharing
    never configured for that group = off with catalog defaults.
  - shared_items: per (owner, tool, recipient group) — the items
    the owner picked for that group (select all / none / per item
    in Settings).

Both foreign keys CASCADE: deleting a tool must not be blocked by
its share rows, and a deleted account takes its sharing setup with
it. The field vocabulary lives in
app/modules/core/sharing_catalog.py.

Revision ID: 0005_sharing
Revises: 0004_page_layouts
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_sharing"
down_revision: str | Sequence[str] | None = "0004_page_layouts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "share_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("recipient_group", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "recipient_group", name="uq_share_config_owner_group"
        ),
    )
    op.create_index(
        "ix_share_configs_owner_id", "share_configs", ["owner_id"]
    )
    op.create_table(
        "shared_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("recipient_group", sa.String(length=50), nullable=False),
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
            "owner_id",
            "tool_id",
            "recipient_group",
            name="uq_shared_item_owner_tool_group",
        ),
    )
    op.create_index("ix_shared_items_owner_id", "shared_items", ["owner_id"])
    op.create_index("ix_shared_items_tool_id", "shared_items", ["tool_id"])


def downgrade() -> None:
    op.drop_index("ix_shared_items_tool_id", table_name="shared_items")
    op.drop_index("ix_shared_items_owner_id", table_name="shared_items")
    op.drop_table("shared_items")
    op.drop_index("ix_share_configs_owner_id", table_name="share_configs")
    op.drop_table("share_configs")
