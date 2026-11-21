"""Catalog lookup jobs (lookup rebuild Phase 4).

The background-job table behind quick-lookup streaming: a
quick lookup that cannot answer completely starts (or joins)
a job for the part number; the job runs the full lookup and
stores the public result for the wizard to poll.

One brand-new table; nothing to verify against the live
schema beyond its absence.

Revision ID: 0116_catalog_lookup_jobs
Revises: 0115_catalog_evidence
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0116_catalog_lookup_jobs"
down_revision = "0115_catalog_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_lookup_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_key", sa.String(length=120), nullable=False),
        sa.Column("model_key", sa.String(length=120), nullable=False),
        sa.Column("upc", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("brand", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_lookup_jobs_brand_key", "catalog_lookup_jobs", ["brand_key"]
    )
    op.create_index(
        "ix_catalog_lookup_jobs_model_key", "catalog_lookup_jobs", ["model_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_lookup_jobs_model_key", table_name="catalog_lookup_jobs")
    op.drop_index("ix_catalog_lookup_jobs_brand_key", table_name="catalog_lookup_jobs")
    op.drop_table("catalog_lookup_jobs")
