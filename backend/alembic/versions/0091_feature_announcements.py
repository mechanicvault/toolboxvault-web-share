"""0091: feature announcements (release machinery, owner rule
2026-11-08) — one new table:

- feature_announcements — the durable record of an
  operator-composed announcement to all current users (Admin ->
  Announcements). The composer lands a row as "queued"; the
  announcements job fans it out to every active account as an
  inbox notification and flips the row to "sent" with the
  recipient count. The per-user copies live in the existing
  notifications table — this table is the history of what was
  sent, when, by whom, and to how many.

Plain table creation from explicit column definitions — no
model __table__ DDL and no hand-written SQL (the 0084/0089/0090
posture): every column name and type is spelled out here and
was verified against the live production schema immediately
before shipping (production at 0090, no feature_announcements
table present).
"""

import sqlalchemy as sa
from alembic import op

revision = "0091_feature_announcements"
down_revision = "0090_appearance_accent_light"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_announcements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=False),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("recipient_count", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_by_name",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("feature_announcements")
