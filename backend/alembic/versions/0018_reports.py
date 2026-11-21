"""Reports module (2026-10-19): saved report configurations.

One table — report_configs. A config is a named report spec
(columns / filters / grouping / sets_mode / sort) stored as JSON;
running it re-derives rows from inventory at read time, so this
migration carries no data and nothing else changes shape.

Built-in presets are code, not rows — nothing to seed.

Revision ID: 0018_reports
Revises: 0017_stripe
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_reports"
down_revision: str | None = "0017_stripe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "columns", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "filters", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("grouping", sa.String(length=30), nullable=False, server_default="none"),
        sa.Column("sets_mode", sa.String(length=20), nullable=False, server_default="summary"),
        sa.Column(
            "sort", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_report_configs_owner_id"), "report_configs", ["owner_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_report_configs_owner_id"), table_name="report_configs")
    op.drop_table("report_configs")
