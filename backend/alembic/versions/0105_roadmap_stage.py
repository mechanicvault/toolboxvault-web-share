"""Roadmap stage (owner rebuild, 2026-11-12).

The What's Coming roadmap becomes an 8-stage task list:
idea -> approved_idea -> awaiting_schedule -> scheduled ->
building_started -> building_finished -> testing -> released.

The `status` column (varchar(20), created by 0047) is renamed
to `stage` and its three legacy values are rewritten in place
— no entry is dropped, retitled, or reordered:

    planned     -> awaiting_schedule  (decided and published,
                                       not scheduled, not built)
    in_progress -> building_started   (work has begun; the
                                       earliest in-build stage)
    shipped     -> released

Every new stage value fits the existing varchar(20) (longest:
'awaiting_schedule' / 'building_finished', 17 chars).

Revision ID: 0105_roadmap_stage
Revises: 0104_content_alert_prefs
"""

import sqlalchemy as sa
from alembic import op

revision = "0105_roadmap_stage"
down_revision = "0104_content_alert_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE roadmap_entries SET status = 'awaiting_schedule' "
        "WHERE status = 'planned'"
    )
    op.execute(
        "UPDATE roadmap_entries SET status = 'building_started' "
        "WHERE status = 'in_progress'"
    )
    op.execute(
        "UPDATE roadmap_entries SET status = 'released' "
        "WHERE status = 'shipped'"
    )
    op.alter_column(
        "roadmap_entries",
        "status",
        new_column_name="stage",
        existing_type=sa.String(20),
        existing_nullable=False,
        server_default="idea",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE roadmap_entries SET stage = 'planned' "
        "WHERE stage IN ('idea', 'approved_idea', 'awaiting_schedule', 'scheduled')"
    )
    op.execute(
        "UPDATE roadmap_entries SET stage = 'in_progress' "
        "WHERE stage IN ('building_started', 'building_finished', 'testing')"
    )
    op.execute(
        "UPDATE roadmap_entries SET stage = 'shipped' WHERE stage = 'released'"
    )
    op.alter_column(
        "roadmap_entries",
        "stage",
        new_column_name="status",
        existing_type=sa.String(20),
        existing_nullable=False,
        server_default="planned",
    )
