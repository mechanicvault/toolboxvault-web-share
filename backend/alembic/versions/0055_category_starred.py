"""Starred categories (owner spec 2026-10-24).

A `starred` flag on the category registry: starred categories
surface as shortcut links in the Inventory view row, capped at
10 per owner (enforced in the service, not the schema). The
flag rides the registry row so renames carry it and deletes /
merge-sources take it with the row.

Revision ID: 0055_category_starred
Revises: 0054_notification_channel_prefs
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0055_category_starred"
down_revision = "0054_notification_channel_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inventory_categories",
        sa.Column(
            "starred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("inventory_categories", "starred")
