"""Catalog library trust status (lookup rebuild Phase 0).

Ryan's order (2026-11-20): rebuild the catalog lookup as an
evidence-gathering agent with a plain-code referee, and a
library that cannot certify itself. Phase 0 stops the
bleeding: every library record gains a trust status, existing
rows are classified by where they actually came from, and
(as code, in library.py) a set's piece list may only be
replaced by a verified list — the old "richer list wins"
guard is what let the contaminated SBUPM246V list (12 real
pieces + 6 Similar-Products wrenches) certify itself.

Backfill by source_kind, verified against the live
production schema 2026-11-20 (the table matches migration
0113 exactly, no status column yet; source_kind values
present: 'seed' x31,209 and 'verified' x1 — no web-walk rows
exist yet, so the candidate class starts empty and grows
from future pulls):
- 'seed'     -> 'seed'     (the dealer catalog extraction)
- 'verified' -> 'verified' (hand-verified corrections)
- everything else -> 'candidate' (web-walk pulls, unproven)

Revision ID: 0114_catalog_trust
Revises: 0113_catalog_library
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0114_catalog_trust"
down_revision = "0113_catalog_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_products",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="candidate",
        ),
    )
    op.execute(
        "UPDATE catalog_products SET status = 'seed' "
        "WHERE source_kind = 'seed'"
    )
    op.execute(
        "UPDATE catalog_products SET status = 'verified' "
        "WHERE source_kind = 'verified'"
    )


def downgrade() -> None:
    op.drop_column("catalog_products", "status")
