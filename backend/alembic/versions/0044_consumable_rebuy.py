"""Consumable re-buy info (completeness audit A7).

The consumable flag shipped without its payload: a mechanic who
burns through blades/discs/fluids had nowhere to record WHERE the
replacement comes from. tools gains the re-buy block — store,
website, SKU/part number, and free notes — edited from the tool
form whenever the consumable flag is set, shown on the detail
page, carried by exports, the change journal (ORM columns), and
the reports column catalog.

Plain text columns, empty-string defaults like the tool's other
free-text fields; existing rows read as "no re-buy info recorded".

Revision ID: 0044_consumable_rebuy
Revises: 0043_directory_warranty_urls
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_consumable_rebuy"
down_revision: str | None = "0043_directory_warranty_urls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("rebuy_store", sa.String(200)),
    ("rebuy_url", sa.String(500)),
    ("rebuy_sku", sa.String(120)),
    ("rebuy_notes", sa.Text),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column(
            "tools",
            sa.Column(name, type_, nullable=False, server_default=""),
        )


def downgrade() -> None:
    for name, _type_ in reversed(_COLUMNS):
        op.drop_column("tools", name)
