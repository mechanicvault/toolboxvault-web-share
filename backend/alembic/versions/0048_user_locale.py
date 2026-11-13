"""User locale preference (audit A17).

Revision ID: 0048_user_locale
Revises: 0047_roadmap_entries
"""

import sqlalchemy as sa
from alembic import op

revision = "0048_user_locale"
down_revision = "0047_roadmap_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("locale", sa.String(5), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("users", "locale")
