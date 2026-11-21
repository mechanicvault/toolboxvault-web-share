"""0082: the reports library (Reports page redesign, owner
2026-11-06).

Three tables, with their definitions WRITTEN INTO this
script (row 116 fix, 2026-11-18 — the original created them
straight off the reports module's live models, so a fresh
build made them with whatever shape the models carry on the
day it runs and any later migration adding to them would
collide; a migration carries the shape as of its own point
in the chain):

- report_templates — the redesigned page's saved reports: a
  catalog report type + its settings + the area it lists in
  (quick | accounting).
- generated_reports — the History: one row per generated file,
  the bytes in object storage under the owner's namespace.
- report_template_seeds — the seed-once marker for the seven
  default templates (a deleted default never resurrects).

No data is seeded here and no existing table is touched: the
defaults are seeded lazily by the service at each user's first
templates read (that's what makes seed-once semantics work for
accounts that already exist).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0082_reports_library"
down_revision = "0081_flyer_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_templates",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("report_type", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("area", sa.String(16), nullable=False),
        sa.Column("settings", PG_JSONB(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_report_templates_owner_id", "report_templates", ["owner_id"]
    )
    op.create_table(
        "generated_reports",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("report_templates.id"),
        ),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("report_type", sa.String(40), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("storage_key", sa.String(600), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("settings", PG_JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_generated_reports_owner_id", "generated_reports", ["owner_id"]
    )
    op.create_index(
        "ix_generated_reports_template_id",
        "generated_reports",
        ["template_id"],
    )
    op.create_table(
        "report_template_seeds",
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column(
            "seeded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("report_template_seeds")
    op.drop_table("generated_reports")
    op.drop_table("report_templates")
