"""Add users.password_login_enabled.

OAuth-created accounts store an unmatchable random password hash, so
"has a password" cannot be inferred from the hash itself. This flag is
the record: TRUE means email+password login works for the account.

Backfill: TRUE for every existing row — all current accounts are email
signups (the one OAuth test account flips itself the moment it sets a
password). Going forward the flag is written at creation:
service.create_oauth_user sets FALSE, email signup sets TRUE.

Revision ID: 0002_password_login_enabled
Revises: 0001_initial
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_password_login_enabled"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "password_login_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "password_login_enabled")
