"""Add user_page_layouts (per-user page block arrangement).

Owner directive 2026-10-17: users choose which blocks appear on each
page they can access, and their order — the layout is a product
feature, stored per account so it follows the user across devices.

One row per (user, page): `blocks` is the ordered JSON list of
{"key": str, "visible": bool} the client saved. Block keys are opaque
to the server (the page block registries live in the frontend); no row
means the user never customized that page and the client renders the
page's registered defaults.

Revision ID: 0004_page_layouts
Revises: 0003_account_types
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_page_layouts"
down_revision: str | Sequence[str] | None = "0003_account_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_page_layouts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("page_key", sa.String(length=64), nullable=False),
        sa.Column("blocks", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "page_key", name="uq_user_page_layout"),
    )
    op.create_index(
        "ix_user_page_layouts_user_id", "user_page_layouts", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_page_layouts_user_id", table_name="user_page_layouts")
    op.drop_table("user_page_layouts")
