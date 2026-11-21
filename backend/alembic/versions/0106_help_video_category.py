"""Help-video category (owner, 2026-11-14).

Adds `category` (string, NOT NULL, default "general") to
`help_videos`: the site area each video teaches. The How-to
Videos page is rebuilt around it — a Website/App toggle on top
and, below it, one tab per category (ALL first) — so a video's
category is set in the Admin video manager when the video is
added. Every existing video lands on "general" (the catalog's
default, support/models.py VIDEO_CATEGORIES).

Bare-safe by construction (the standing migration gate): this
file imports alembic + sqlalchemy only and names its table and
column literally. Column verified against the model that owns
it: help_videos — support/models.py HelpVideo (section, added
the same way in 0070, is the pattern column: String, nullable
False, default "website").
"""

import sqlalchemy as sa
from alembic import op

revision = "0106_help_video_category"
down_revision = "0105_roadmap_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "help_videos",
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            server_default="general",
        ),
    )


def downgrade() -> None:
    op.drop_column("help_videos", "category")
