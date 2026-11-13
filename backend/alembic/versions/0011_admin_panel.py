"""Admin panel expansion (Phase A2, owner doctrine 2026-10-18:
admin = God privileges, run from the panel, never via this chat).

What lands:

1. users.role — the community role ladder's foundation
   (user | moderator | community_admin). Separate from the group
   set and from is_operator; the community modules consume it
   when they ship. Existing accounts land on "user".
2. users.is_active — soft deactivation: sign-in blocked, sessions
   revoked, nothing deleted, fully reversible. Existing accounts
   land on true.
3. banned_emails — operator bans on an ADDRESS, enforced at
   signup, password sign-in, and social sign-in; banning revokes
   the account's live sessions. Deleting nothing, ever.
4. audit_log — one row per mutating operator action (actor id +
   email snapshot, dotted action, target, JSON detail), written
   by every /api/admin/* endpoint through core's audit service
   and read by the Admin → Audit section.

Downgrade drops it all in reverse.

Revision ID: 0011_admin_panel
Revises: 0010_billing
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_admin_panel"
down_revision: str | Sequence[str] | None = "0010_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role", sa.String(length=32), nullable=False, server_default="user"
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_table(
        "banned_emails",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "reason", sa.String(length=500), nullable=False, server_default=""
        ),
        sa.Column("banned_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "actor_email",
            sa.String(length=320),
            nullable=False,
            server_default="",
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column(
            "target", sa.String(length=200), nullable=False, server_default=""
        ),
        sa.Column(
            "detail", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_user_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("banned_emails")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
