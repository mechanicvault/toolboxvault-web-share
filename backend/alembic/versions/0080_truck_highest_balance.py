"""Truck accounts — the HIGHEST CREDIT LIMIT (owner's label +
rule, 2026-11-05; build, 2026-11-06).

Every truck account gains `highest_balance`: the highest
balance the account has ever stood at — the peak of what was
owed. The owner's worked example: open at $100 → highest is
$100; the balance later hits $3,100 → highest is $3,100; pay
it down → highest STAYS $3,100. It is system-maintained (no
form writes it), BOTH seats see it, and it never decreases —
which is exactly why it is a STORED column and not a
read-time computation over the ledger: a later backdated or
corrective entry must never be able to rewrite the peak the
account genuinely reached.

Backfill: each existing account's peak is the maximum RUNNING
balance across its ledger in the ledger's canonical order
(the service's list_entries order: entry_date, created_at,
id), floored at zero — the same number the entries prove.
The ledger is append-only (entries are never edited or
deleted; balance_of sums every row), so the backfill walks
every row. Accounts with no entries keep the server
default 0.

DDL goes through SQLAlchemy ops; the backfill is a read +
per-account UPDATE whose table/column names (truck_entries:
account_id, amount, entry_date, created_at, id;
truck_accounts: id) were verified against `\\d
truck_accounts` / `\\d truck_entries` on production BEFORE
this was written, per the standing migration rule from the
2026-11-05 outage.

Revision ID: 0080_truck_highest_balance
Revises: 0079_claims_overhaul
Create Date: 2026-11-06
"""

from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "0080_truck_highest_balance"
down_revision = "0079_claims_overhaul"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "truck_accounts",
        sa.Column(
            "highest_balance",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT account_id, amount FROM truck_entries"
            " ORDER BY account_id, entry_date, created_at, id"
        )
    ).all()
    running: dict = {}
    peaks: dict = {}
    for account_id, amount in rows:
        balance = running.get(account_id, Decimal("0")) + Decimal(amount)
        running[account_id] = balance
        if balance > peaks.get(account_id, Decimal("0")):
            peaks[account_id] = balance
    for account_id, peak in peaks.items():
        if peak > 0:
            bind.execute(
                sa.text(
                    "UPDATE truck_accounts SET highest_balance = :peak"
                    " WHERE id = :account_id"
                ).bindparams(
                    sa.bindparam("peak", type_=sa.Numeric(12, 2))
                ),
                {"peak": peak, "account_id": account_id},
            )


def downgrade() -> None:
    op.drop_column("truck_accounts", "highest_balance")
