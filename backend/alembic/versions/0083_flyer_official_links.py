"""Flyer gate + official links (owner orders, 2026-11-06
22:15/22:20): the platform-kept official flyer link lands on
the directory company (dealer_companies.official_flyer_url —
researched corporate data, the warranty_url discipline), and
the flyer spot gains the SYSTEM pull's dedupe state
(flyer_sources.auto_hash / auto_checked_at) so a changed
official edition posts under the company's spot and an
unchanged one never re-posts. The posting-gate tightening
itself is service-layer only (rights checks, no schema).

Plain column adds with server defaults only — no model
__table__ DDL, no hand-written SQL, so nothing here can drift
from a column name or strand an FK in a bare process.
"""

import sqlalchemy as sa
from alembic import op

revision = "0083_flyer_official_links"
down_revision = "0082_reports_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dealer_companies",
        sa.Column(
            "official_flyer_url",
            sa.String(500),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "flyer_sources",
        sa.Column("auto_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "flyer_sources",
        sa.Column(
            "auto_checked_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("flyer_sources", "auto_checked_at")
    op.drop_column("flyer_sources", "auto_hash")
    op.drop_column("dealer_companies", "official_flyer_url")
