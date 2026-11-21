"""Print file public switch (owner, 2026-11-14).

print_files gains `is_public`: the publisher's own on/off
switch for the public shelf. Every existing file starts ON
(server default true) — nothing changes for any file already
published; turning it off takes the file out of the public's
view (browse, search, detail, downloads) while the publisher
keeps full sight of it in My Files.

Revision ID: 0107_print_file_is_public
Revises: 0106_help_video_category
Create Date: 2026-11-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0107_print_file_is_public"
down_revision = "0106_help_video_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_files",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("print_files", "is_public")
