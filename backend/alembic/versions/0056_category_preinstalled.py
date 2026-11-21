"""Preinstalled starter categories (owner spec 2026-10-25).

Adds `system_key` to the category registry: NULL for a user's
own categories, one of "batteries" | "hand_tools" |
"power_tools" | "pneumatic_tools" for the four starter
categories every account is seeded with (starred by default,
never deletable; "batteries" is also fixed-name). The seeding
itself is service code (inventory.service
.ensure_starter_categories) — it runs at account creation and
was run once for the accounts that already existed; this
migration is schema only. The unique index keeps one row per
starter per owner (NULLs stay unconstrained, as everywhere).

Revision ID: 0056_category_preinstalled
Revises: 0055_category_starred
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0056_category_preinstalled"
down_revision = "0055_category_starred"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inventory_categories",
        sa.Column("system_key", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "uq_inventory_categories_owner_system_key",
        "inventory_categories",
        ["owner_id", "system_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_inventory_categories_owner_system_key",
        table_name="inventory_categories",
    )
    op.drop_column("inventory_categories", "system_key")
