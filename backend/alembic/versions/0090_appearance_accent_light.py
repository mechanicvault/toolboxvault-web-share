"""0090: per-mode accent (owner order, 2026-11-08) — one new
column on users:

- appearance_accent_light — the account's LIGHT-mode accent
  pick. The accent becomes a per-mode memory: the existing
  appearance_accent column is the dark-mode pick (the value
  every account saved before this split existed), and this
  column holds the light-mode pick. NULL = no pick in light
  mode; the client applies the light default (silver, the
  palette's grey/silver preset) until the user picks a color
  while in light. Existing rows land NULL, which is simply
  true: no light-mode pick existed before this.

Plain column add, nullable, no server default, no model
__table__ DDL and no hand-written SQL — the 0084/0089 posture:
nothing here can drift from a column name or strand an FK in
a bare process. Column shape mirrors appearance_accent on the
same table (character varying(16), nullable — verified against
the live production schema immediately before shipping).
"""

import sqlalchemy as sa
from alembic import op

revision = "0090_appearance_accent_light"
down_revision = "0089_agent_invite_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "appearance_accent_light",
            sa.String(length=16),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "appearance_accent_light")
