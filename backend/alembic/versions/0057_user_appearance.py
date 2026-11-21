"""Account-held appearance (owner ruling, 2026-10-25).

Adds the appearance triple to `users`: mode (dark|light),
accent (hex color), theme. All NULLABLE with no default —
NULL means "this account has never saved an appearance",
and the client keeps its built-in defaults (dark + orange)
for such accounts, so no existing account's look changes
under it. Once a signed-in user changes any of the three,
the client saves all three through PATCH /me and the
account becomes the source of truth at every sign-in,
on every browser and device; the browser's localStorage
copy remains only as a pre-login cache.

Revision ID: 0057_user_appearance
Revises: 0056_category_preinstalled
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0057_user_appearance"
down_revision = "0056_category_preinstalled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("appearance_mode", sa.String(8), nullable=True)
    )
    op.add_column(
        "users", sa.Column("appearance_accent", sa.String(16), nullable=True)
    )
    op.add_column(
        "users", sa.Column("appearance_theme", sa.String(32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "appearance_theme")
    op.drop_column("users", "appearance_accent")
    op.drop_column("users", "appearance_mode")
