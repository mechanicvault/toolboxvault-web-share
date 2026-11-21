"""Catalog evidence store (lookup rebuild Phase 1).

Every observation a lookup run makes — a recorded data
response, a page map, a section read — lands here, scrubbed,
keyed by brand + part number, so the agent's facts can point
at evidence and runs can be replayed offline in tests.

One brand-new table; there is nothing to verify against the
live schema beyond its absence (checked 2026-11-20 against
production at 0113 + the Phase 0 column).

Revision ID: 0115_catalog_evidence
Revises: 0114_catalog_trust
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0115_catalog_evidence"
down_revision = "0114_catalog_trust"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_key", sa.String(length=120), nullable=False),
        sa.Column("model_key", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("section", sa.String(length=400), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_evidence_brand_key", "catalog_evidence", ["brand_key"]
    )
    op.create_index(
        "ix_catalog_evidence_model_key", "catalog_evidence", ["model_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_evidence_model_key", table_name="catalog_evidence")
    op.drop_index("ix_catalog_evidence_brand_key", table_name="catalog_evidence")
    op.drop_table("catalog_evidence")
