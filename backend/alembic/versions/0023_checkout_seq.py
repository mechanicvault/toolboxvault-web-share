"""Checkout history ordering (hardening 2026-10-19): a monotonic
`seq` on checkouts.

The history order was (created_at DESC, id DESC) — but created_at
ties constantly (SQLite's now() has second resolution; a single
Postgres transaction shares one timestamp too) and the id is a
random UUID, so tied rows ordered arbitrarily. That made
test_history_accumulates_newest_first a coin flip and, worse, made
the production history order unstable for same-tick lends.

seq numbers every row in insertion order: existing rows are
backfilled in (created_at, id) order, and new rows are assigned by
the model's before_insert hook — on Postgres from the real
`checkouts_seq` sequence created here (set to continue from the
backfill), on SQLite from max+1 inside the insert transaction.

Revision ID: 0023_checkout_seq
Revises: 0022_dealer_portal
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_checkout_seq"
down_revision: str | None = "0022_dealer_portal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute("CREATE SEQUENCE IF NOT EXISTS checkouts_seq")

    op.add_column(
        "checkouts", sa.Column("seq", sa.BigInteger(), nullable=True)
    )

    if is_postgres:
        # Number existing rows oldest-first in one pass, then park
        # the sequence past the highest assigned value so the app's
        # nextval draws continue from there.
        op.execute(
            """
            WITH ordered AS (
                SELECT id,
                       ROW_NUMBER() OVER (ORDER BY created_at, id) AS rn
                FROM checkouts
            )
            UPDATE checkouts AS c
            SET seq = o.rn
            FROM ordered AS o
            WHERE o.id = c.id
            """
        )
        highest = bind.execute(
            sa.text("SELECT MAX(seq) FROM checkouts")
        ).scalar()
        if highest is not None:
            op.execute(f"SELECT setval('checkouts_seq', {int(highest)})")
    else:
        # SQLite: the same (created_at, id) numbering, row by row.
        rows = bind.execute(
            sa.text("SELECT id FROM checkouts ORDER BY created_at, id")
        ).fetchall()
        for number, (row_id,) in enumerate(rows, start=1):
            bind.execute(
                sa.text("UPDATE checkouts SET seq = :n WHERE id = :i"),
                {"n": number, "i": row_id},
            )

    with op.batch_alter_table("checkouts") as batch_op:
        batch_op.alter_column(
            "seq", existing_type=sa.BigInteger(), nullable=False
        )


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("checkouts") as batch_op:
        batch_op.drop_column("seq")
    if bind.dialect.name == "postgresql":
        op.execute("DROP SEQUENCE IF EXISTS checkouts_seq")
