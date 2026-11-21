"""Roadmap entries (audit A15).

Revision ID: 0047_roadmap_entries
Revises: 0046_policy_depth_business_use
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0047_roadmap_entries"
down_revision = "0046_policy_depth_business_use"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roadmap_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("roadmap_entries")
