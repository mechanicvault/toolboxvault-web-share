"""Messaging + Community Parts pool (2026-10-19).

Three pieces land together (the community suite's first build):

- users gain the community contact preferences: public_area_label
  (a coarse area, never an address), contact_phone (the number the
  user may publish), show_phone (the opt-in, default OFF — a phone
  rides a public payload only while its owner chose to show it).

- parts gain the pool columns: the STANDARD vehicle fields the
  community index searches on (year, make, model, engine — core
  columns because owners name their custom fields differently),
  the owner's category label, an optional asking_price, and the
  per-part listing overrides (public_area_label, visibility,
  show_phone_override — all NULL = inherit). part_pool_settings
  holds each owner's defaults (default_visibility starts
  "private"; category_visibility maps label -> public|private).

- messaging tables: message_threads (the sorted pair + anchor +
  quarantine status), messages (append-only, firewall status +
  flags, ordered by the `message_seq` Postgres sequence created
  here — the journal pattern from 0027), message_thread_states
  (per-participant read marker + hidden), user_blocks (silent),
  message_reports (the moderation queue's feed).

No module_access seed for messaging: the control service falls
back to the manifest's default_groups (all four) when a module
has no rows — the same posture every post-0008 module shipped
with. No system-setting seeds: the spam config and the pool
switch both read code defaults until an operator edits them.

Revision ID: 0028_messaging_pool
Revises: 0027_audit_trail
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_messaging_pool"
down_revision: str | None = "0027_audit_trail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE SEQUENCE IF NOT EXISTS message_seq")

    # -- users: community contact preferences -------------------------
    op.add_column(
        "users",
        sa.Column(
            "public_area_label",
            sa.String(length=120),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "contact_phone", sa.String(length=40), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "show_phone",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # -- parts: pool columns -------------------------------------------
    op.add_column("parts", sa.Column("year", sa.Integer(), nullable=True))
    op.add_column(
        "parts",
        sa.Column("make", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "parts",
        sa.Column("model", sa.String(length=150), nullable=False, server_default=""),
    )
    op.add_column(
        "parts",
        sa.Column(
            "engine", sa.String(length=100), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "parts",
        sa.Column(
            "category", sa.String(length=100), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "parts", sa.Column("asking_price", sa.Numeric(12, 2), nullable=True)
    )
    op.add_column(
        "parts", sa.Column("public_area_label", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "parts", sa.Column("visibility", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "parts", sa.Column("show_phone_override", sa.Boolean(), nullable=True)
    )
    op.create_index("ix_parts_category", "parts", ["category"])

    op.create_table(
        "part_pool_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "default_visibility",
            sa.String(length=10),
            nullable=False,
            server_default="private",
        ),
        sa.Column(
            "category_visibility",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", name="uq_part_pool_settings_owner"),
    )
    op.create_index(
        "ix_part_pool_settings_owner_id", "part_pool_settings", ["owner_id"]
    )

    # -- messaging ------------------------------------------------------
    op.create_table(
        "message_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("participant_low_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "participant_high_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "anchor_type", sa.String(length=30), nullable=False, server_default=""
        ),
        sa.Column("anchor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "anchor_title", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="request"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["participant_low_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["participant_high_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_message_threads_participant_low_id",
        "message_threads",
        ["participant_low_id"],
    )
    op.create_index(
        "ix_message_threads_participant_high_id",
        "message_threads",
        ["participant_high_id"],
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="sent"
        ),
        sa.Column(
            "flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["message_threads.id"]),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_thread_id", "messages", ["thread_id"])
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"])

    op.create_table(
        "message_thread_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "last_read_seq", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "hidden", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["message_threads.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "user_id", name="uq_thread_state_user"),
    )
    op.create_index(
        "ix_message_thread_states_thread_id", "message_thread_states", ["thread_id"]
    )
    op.create_index(
        "ix_message_thread_states_user_id", "message_thread_states", ["user_id"]
    )

    op.create_table(
        "user_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blocker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blocked_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_block_pair"),
    )
    op.create_index("ix_user_blocks_blocker_id", "user_blocks", ["blocker_id"])
    op.create_index("ix_user_blocks_blocked_id", "user_blocks", ["blocked_id"])

    op.create_table(
        "message_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "reason", sa.String(length=500), nullable=False, server_default=""
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="open"
        ),
        sa.Column(
            "resolution", sa.String(length=500), nullable=False, server_default=""
        ),
        sa.Column("resolved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["message_threads.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_reports_thread_id", "message_reports", ["thread_id"])
    op.create_index(
        "ix_message_reports_reporter_id", "message_reports", ["reporter_id"]
    )


def downgrade() -> None:
    op.drop_table("message_reports")
    op.drop_table("user_blocks")
    op.drop_table("message_thread_states")
    op.drop_table("messages")
    op.drop_table("message_threads")
    op.drop_table("part_pool_settings")
    op.drop_index("ix_parts_category", table_name="parts")
    for column in (
        "show_phone_override",
        "visibility",
        "public_area_label",
        "asking_price",
        "category",
        "engine",
        "model",
        "make",
        "year",
    ):
        op.drop_column("parts", column)
    for column in ("show_phone", "contact_phone", "public_area_label"):
        op.drop_column("users", column)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP SEQUENCE IF EXISTS message_seq")
