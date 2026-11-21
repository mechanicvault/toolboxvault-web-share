"""Usernames — the public identity (sheet row 144).

Owner directive 2026-11-18: every account carries a unique
username, and it replaces the real name on every surface other
users see (forum, comments, print publisher, ...). This
migration adds the columns:

- users.username — the display form, NULL until picked
  (signup forces the pick; pre-existing accounts are gated to
  pick at next sign-in).
- users.username_key — the uniqueness form (lowercase,
  alphanumerics only), unique-indexed; NULL keys never
  collide, so unpicked accounts coexist.
- users.username_changed_at — last set stamp; changes are
  limited to once every 6 months from it.

Backfill: god-tier accounts are named "Toolbox Vault" by
default (the reserved name only admin accounts may hold).

Revision ID: 0112_usernames
Revises: 0111_sharing_item_fks
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0112_usernames"
down_revision = "0111_sharing_item_fks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("username", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("username_key", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "username_changed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.create_index(
        "uq_users_username_key", "users", ["username_key"], unique=True
    )
    op.execute(
        "UPDATE users SET username = 'Toolbox Vault', "
        "username_key = 'toolboxvault', "
        "username_changed_at = CURRENT_TIMESTAMP "
        "WHERE tier = 'god' AND username IS NULL"
    )


def downgrade() -> None:
    op.drop_index("uq_users_username_key", table_name="users")
    op.drop_column("users", "username_changed_at")
    op.drop_column("users", "username_key")
    op.drop_column("users", "username")
