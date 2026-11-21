"""Rail pin (widget options Wave 1, owner design 2026-11-02):
users.rail_pinned — the account-held choice to keep the left
menu rail open, mirroring the appearance triple's posture
(account-held, hydrated at sign-in, wins on every device).

Nullable with no server default: NULL = never set (the client
reads it as unpinned — the rail's hover behavior, unchanged);
True = pinned open; False = an explicit unpin. Existing rows
land on NULL, so every legacy account's rail behaves exactly
as it does today until the owner of the account pins it.

Revision ID: 0071_rail_pinned
Revises: 0070_help_support
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0071_rail_pinned"
down_revision = "0070_help_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("rail_pinned", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "rail_pinned")
