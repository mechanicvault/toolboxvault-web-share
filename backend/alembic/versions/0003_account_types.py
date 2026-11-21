"""Add users.account_types (account group set).

Owner directive 2026-10-17 (as corrected the same day): every user
belongs to one or MORE groups — mechanic_technician, shop_company,
tool_dealer, insurance — picked at signup (at least one required),
and the account number carries the segment formed by ALL the
account's group letters in canonical order (TV-MD-…… for a mechanic
who also deals).

The set is stored as a JSON array. Existing rows are backfilled to
the empty array by the server default: empty = "not chosen yet" —
pre-group accounts keep their plain TV-###### numbers until the
owner picks a set in the app, at which point the number is
re-segmented (digits unchanged). OAuth signups likewise start with
the empty set; the app prompts once after first login.

(This migration supersedes a single-value draft written earlier the
same day; that draft never deployed, so the set design lands
directly as 0003.)

Revision ID: 0003_account_types
Revises: 0002_password_login_enabled
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_account_types"
down_revision: str | Sequence[str] | None = "0002_password_login_enabled"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "account_types",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "account_types")
