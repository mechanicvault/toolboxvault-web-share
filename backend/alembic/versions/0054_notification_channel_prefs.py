"""Per-category notification channel preferences (2026-10-24).

Owner item 12: Settings -> Notifications gains, per
notification category, an EMAIL on/off choice (the bell stays
the always-on base layer). The table is channel-shaped —
(channel is a plain string: "email" today, push/sms later
without a rebuild) — and a row exists only where a user
changed a category away from its default.

Revision ID: 0054_notification_channel_prefs
Revises: 0053_support_status_under_review
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0054_notification_channel_prefs"
down_revision = "0053_support_status_under_review"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "notification_channel_prefs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "category", "channel", name="uq_notification_channel_pref"
        ),
    )
    op.create_index(
        "ix_notification_channel_prefs_user_id",
        "notification_channel_prefs",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_channel_prefs_user_id",
        table_name="notification_channel_prefs",
    )
    op.drop_table("notification_channel_prefs")
