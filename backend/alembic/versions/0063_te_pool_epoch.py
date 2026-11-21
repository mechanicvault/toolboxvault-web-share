"""Tool Expansion pool epoch counter (scale fix follow-up, 2026-10-26).

One row: the version counter for the Tool Expansion pool snapshot.
Every pool-relevant write bumps it inside its own transaction, so
with several API workers each process can tell — with one primary-
key read — that its cached pool derivation went stale, instead of
waiting out the snapshot TTL. Seeded here; the ORM model
(PoolEpoch) keeps create_all-based setups in step.
"""

import sqlalchemy as sa
from alembic import op

revision = "0063_te_pool_epoch"
down_revision = "0062_model_norm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "te_pool_epoch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("epoch", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.execute(
        "INSERT INTO te_pool_epoch (id, epoch) "
        "SELECT 1, 0 WHERE NOT EXISTS (SELECT 1 FROM te_pool_epoch WHERE id = 1)"
    )


def downgrade() -> None:
    op.drop_table("te_pool_epoch")
