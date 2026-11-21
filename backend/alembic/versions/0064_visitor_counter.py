"""Teaser visitor counter (owner order, 2026-10-26).

One row: the unique-visitor count the teaser page shows as bare
digits. Bumped by a single atomic UPDATE per newly-counted
browser (the te_pool_epoch pattern, 0063); the counting rules
(counted-cookie, automation + operator IP exclusions) live in
core/teaser.py. Seeded here; the ORM model (VisitorCounter)
keeps create_all-based setups in step.
"""

import sqlalchemy as sa
from alembic import op

revision = "0064_visitor_counter"
down_revision = "0063_te_pool_epoch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visitor_counter",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.execute(
        "INSERT INTO visitor_counter (id, count) "
        "SELECT 1, 0 WHERE NOT EXISTS (SELECT 1 FROM visitor_counter WHERE id = 1)"
    )


def downgrade() -> None:
    op.drop_table("visitor_counter")
