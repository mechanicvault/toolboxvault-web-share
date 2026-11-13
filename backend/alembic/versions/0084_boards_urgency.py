"""Boards urgency (owner order, 2026-11-06 22:45): a bug
report or feature request carries the filer's urgency —
low | medium | high, chosen on the filing form's 3-position
toggle, default medium; the filer can never edit it after
submission, moderators can (feedback_posts.urgency).

Plain column add with a server default only — no model
__table__ DDL, no hand-written SQL, so nothing here can
drift from a column name or strand an FK in a bare process.
Existing rows land on 'medium', the picker's own default.
"""

import sqlalchemy as sa
from alembic import op

revision = "0084_boards_urgency"
down_revision = "0083_flyer_official_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feedback_posts",
        sa.Column(
            "urgency",
            sa.String(10),
            nullable=False,
            server_default="medium",
        ),
    )


def downgrade() -> None:
    op.drop_column("feedback_posts", "urgency")
