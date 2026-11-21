"""Asset history (2026-10-20): the REPLACED marker on tools +
batteries.

replaced_on (the owner's swap date), replaced_by_item_id (a
PLAIN column, no FK — the borrowing-ledger pattern: the marker
must survive the replacement record being deleted, and the id
may name a tool OR a battery, so no single table could hold the
FK), replaced_note (free text, '' when unset).

Replaced items stay in the entitlement active set — the columns
are pure history; nothing in billing reads them.

Revision ID: 0039_asset_replaced
Revises: 0038_warranty_requester_fk
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_asset_replaced"
down_revision: str | None = "0038_warranty_requester_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("tools", "batteries")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("replaced_on", sa.Date(), nullable=True))
        op.add_column(
            table,
            sa.Column("replaced_by_item_id", sa.Uuid(), nullable=True),
        )
        op.add_column(
            table,
            sa.Column(
                "replaced_note",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "replaced_note")
        op.drop_column(table, "replaced_by_item_id")
        op.drop_column(table, "replaced_on")
