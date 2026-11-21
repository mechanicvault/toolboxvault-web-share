"""Reports alignment pass (2026-10-19) — profile contact details
for the Prepared-For block + saved-spec display options.

Ryan's app inventory report is the format benchmark; its
PREPARED FOR block carries the owner's name, address, phone and
email. The website profile had name + email only, so:

- users.phone — the owner's own phone for paperwork (reports,
  claims). Deliberately NOT the community contact_phone: that one
  is the publishable number behind the show_phone opt-in; this one
  is private account data that only ever renders on the owner's
  own generated documents.
- users.postal_address — free-form postal address (may span
  lines), same private-paperwork purpose.

Both optional, default "" — unset renders as ABSENT on a report,
never as a blank line.

- report_configs.options — the spec-level display options that
  are not columns/filters/grouping/sort: show_row_numbers,
  show_summary, orientation (reports alignment). JSON so the next
  display option doesn't need another column. Existing rows get
  {} — the service reads missing keys as the legacy defaults
  (no row numbers, summary on, landscape).

Revision ID: 0032_reports_alignment
Revises: 0031_pkgc_sharing_insurance
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_reports_alignment"
down_revision: str | None = "0031_pkgc_sharing_insurance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("phone", sa.String(40), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column(
            "postal_address", sa.String(500), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "report_configs",
        sa.Column(
            "options",
            postgresql.JSONB,
            nullable=False,
            # Plain literal (no ::jsonb cast) so the DDL parses on
            # SQLite too — Postgres coerces the literal to jsonb.
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("report_configs", "options")
    op.drop_column("users", "postal_address")
    op.drop_column("users", "phone")
