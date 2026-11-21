"""Catalog confirmations counter (lookup rebuild Phase 5).

catalog_products gains `confirmations`: how many independent
later runs re-sighted the entry with the same complete piece
list — the corroboration behind two-run promotion from
candidate to verified.

The column is added NOT NULL with a server default of 0, so
every existing row starts unconfirmed; nothing else changes.

Revision ID: 0117_catalog_confirmations
Revises: 0116_catalog_lookup_jobs
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0117_catalog_confirmations"
down_revision = "0116_catalog_lookup_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_products",
        sa.Column(
            "confirmations",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("catalog_products", "confirmations")
