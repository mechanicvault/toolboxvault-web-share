"""Truck accounts — the SYSTEM account number (owner rule,
2026-11-17; sheet row 63).

Every truck account gains `account_number`: "TV-T-000123",
assigned once when the account is created and never changed.
The owner's words: "Each truck account should get a system
account number. This account number will likely only be used
by our system so it is not to be made a prominent part of the
showing system to the user, more of a side item. This will
help in identifying accounts differences" — the same rule that
adds the one-open-account-per-agent enforcement in the service.

Existing accounts are backfilled oldest-first in (created_at,
id) order — the 0023 checkout-seq shape: on Postgres the real
`truck_account_number_seq` sequence is created here and parked
past the backfill so the model's before_insert nextval draws
continue from it; on SQLite the rows are numbered one by one
and the model's hook continues from max+1. The column lands
NOT NULL with a unique index: a number names exactly one
account, closed ones included, forever.

DDL names (truck_accounts: id, created_at) were verified
against the live production schema before this was written,
per the standing migration rule.

Revision ID: 0108_truck_account_number
Revises: 0107_print_file_is_public
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0108_truck_account_number"
down_revision = "0107_print_file_is_public"
branch_labels = None
depends_on = None


def _format(value: int) -> str:
    return f"TV-T-{value:06d}"


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute(
            "CREATE SEQUENCE IF NOT EXISTS truck_account_number_seq"
        )

    op.add_column(
        "truck_accounts",
        sa.Column("account_number", sa.String(20), nullable=True),
    )

    if is_postgres:
        op.execute(
            """
            WITH ordered AS (
                SELECT id,
                       ROW_NUMBER() OVER (ORDER BY created_at, id) AS rn
                FROM truck_accounts
            )
            UPDATE truck_accounts AS a
            SET account_number = 'TV-T-' || LPAD(o.rn::text, 6, '0')
            FROM ordered AS o
            WHERE o.id = a.id
            """
        )
        highest = bind.execute(
            sa.text("SELECT COUNT(*) FROM truck_accounts")
        ).scalar()
        if highest:
            op.execute(
                f"SELECT setval('truck_account_number_seq', {int(highest)})"
            )
    else:
        rows = bind.execute(
            sa.text(
                "SELECT id FROM truck_accounts ORDER BY created_at, id"
            )
        ).fetchall()
        for number, (row_id,) in enumerate(rows, start=1):
            bind.execute(
                sa.text(
                    "UPDATE truck_accounts SET account_number = :n"
                    " WHERE id = :i"
                ),
                {"n": _format(number), "i": row_id},
            )

    with op.batch_alter_table("truck_accounts") as batch_op:
        batch_op.alter_column(
            "account_number", existing_type=sa.String(20), nullable=False
        )
    op.create_index(
        "ix_truck_accounts_account_number",
        "truck_accounts",
        ["account_number"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index(
        "ix_truck_accounts_account_number", table_name="truck_accounts"
    )
    with op.batch_alter_table("truck_accounts") as batch_op:
        batch_op.drop_column("account_number")
    if bind.dialect.name == "postgresql":
        op.execute("DROP SEQUENCE IF EXISTS truck_account_number_seq")
