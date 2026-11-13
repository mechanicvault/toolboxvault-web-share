"""Email flows (transactional email phase, owner decisions
2026-10-18): the provider seam's outbox, password-reset tokens,
and email-change tokens.

What lands:

1. email_outbox — every outbound email recorded by the provider
   seam (app/core/notifications.py): recipient, subject, kind,
   body, provider (dev | resend), status (logged | sent |
   failed). Pre-launch the provider is "dev" (nothing leaves the
   server; rows are the drill record); the Resend key flips it
   live with no schema change.
2. password_reset_tokens — one-time reset tokens, hash-only,
   1-hour expiry (config password_reset_expire_hours). The
   forgot-password flow is the fix for "a forgotten password
   today = lockout".
3. email_change_tokens — one pending email change per token:
   the new address is confirmed by a link sent TO that address
   before users.email moves. The row doubles as the pending
   state Settings displays.

All three are new tables; nothing existing is touched. The
verification-gating switch (auth.require_email_verification)
lives in system_settings — no DDL for it here.

Downgrade drops the three tables.

Revision ID: 0012_email_flows
Revises: 0011_admin_panel
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_email_flows"
down_revision: str | Sequence[str] | None = "0011_admin_panel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _token_table(name: str, extra: list[sa.Column]) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        *extra,
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(f"ix_{name}_user_id", name, ["user_id"])


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column(
            "subject", sa.String(length=500), nullable=False, server_default=""
        ),
        sa.Column(
            "kind", sa.String(length=50), nullable=False, server_default="generic"
        ),
        sa.Column("body", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "provider", sa.String(length=20), nullable=False, server_default="dev"
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="logged"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_outbox_recipient", "email_outbox", ["recipient"])
    _token_table("password_reset_tokens", [])
    _token_table(
        "email_change_tokens",
        [sa.Column("new_email", sa.String(length=320), nullable=False)],
    )


def downgrade() -> None:
    op.drop_index("ix_email_change_tokens_user_id", table_name="email_change_tokens")
    op.drop_table("email_change_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_email_outbox_recipient", table_name="email_outbox")
    op.drop_table("email_outbox")
