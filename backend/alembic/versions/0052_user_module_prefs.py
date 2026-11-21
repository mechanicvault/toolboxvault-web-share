"""Per-user module on/off switches (2026-10-24).

A row in user_module_prefs exists only where a user flipped a
feature module's switch for themselves; absence of a row means
the module is on for that user (subject to the operator layer).
The switches only narrow what the operator already allows —
they never grant, and they never touch the user's data.

Revision ID: 0052_user_module_prefs
Revises: 0051_platform_drive_connection
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0052_user_module_prefs"
down_revision = "0051_platform_drive_connection"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "user_module_prefs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("module_id", sa.String(64), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "module_id", name="uq_user_module_pref"),
    )
    op.create_index(
        "ix_user_module_prefs_user_id", "user_module_prefs", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_module_prefs_user_id", table_name="user_module_prefs")
    op.drop_table("user_module_prefs")
