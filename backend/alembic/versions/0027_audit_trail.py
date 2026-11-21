"""User audit trail + restore (owner feature note 2026-10-19).

Every user's own content gains a change journal and restore
markers, and deleted files gain a retention tombstone:

- change_journal — one row per create / update / delete of a
  user-owned record, with the full before + after snapshot, the
  actor, and a `restorable` flag (two-party records — borrowing
  rows, peer shares — and filed-claim changes are journaled for
  visibility only and never inverted). `seq` is the monotonic
  insertion order the markers watermark against; on Postgres it
  draws from the real `change_journal_seq` sequence created here
  (the model's before_insert hook takes max+1 on SQLite, the
  checkouts pattern from 0023).
- restore_markers — the points an account can roll back to. Every
  EXISTING account gets its baseline here (journal_seq 0: the
  journal starts empty, so "before anything happened" is exactly
  right — there is no history before this deploy and the UI says
  so honestly).
- retained_files — tombstones for storage objects whose records
  stopped referencing them. The purge seam hard-deletes rows +
  objects older than the admin setting `audit.retention_days`,
  seeded here at 180.

Revision ID: 0027_audit_trail
Revises: 0026_parts
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_audit_trail"
down_revision: str | None = "0026_parts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute("CREATE SEQUENCE IF NOT EXISTS change_journal_seq")

    op.create_table(
        "change_journal",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("module", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("marker_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "restorable", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("label", sa.String(length=300), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_change_journal_user_id", "change_journal", ["user_id"])
    op.create_index("ix_change_journal_entity_id", "change_journal", ["entity_id"])
    op.create_index(
        "ix_change_journal_user_seq", "change_journal", ["user_id", "seq"]
    )

    op.create_table(
        "restore_markers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "label", sa.String(length=200), nullable=False, server_default=""
        ),
        sa.Column(
            "kind", sa.String(length=20), nullable=False, server_default="manual"
        ),
        sa.Column(
            "journal_seq", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_restore_markers_user_id", "restore_markers", ["user_id"]
    )

    op.create_table(
        "retained_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "entity_type", sa.String(length=50), nullable=False, server_default=""
        ),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_retained_files_user_id", "retained_files", ["user_id"])

    # The retention window, as an operator setting (Admin →
    # Settings edits it from here on). Seeded only when absent so
    # a re-run never stomps an operator's choice.
    settings_table = sa.table(
        "system_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.JSON),
    )
    existing = bind.execute(
        sa.select(settings_table.c.key).where(
            settings_table.c.key == "audit.retention_days"
        )
    ).first()
    if existing is None:
        op.bulk_insert(settings_table, [{"key": "audit.retention_days", "value": 180}])

    # One-time baseline for every account that already exists: the
    # journal starts empty, so the baseline watermark is 0 and a
    # restore to it unwinds everything journaled from now on.
    if is_postgres:
        op.execute(
            """
            INSERT INTO restore_markers (id, user_id, label, kind, journal_seq)
            SELECT gen_random_uuid(), id, 'Account created', 'baseline', 0
            FROM users
            """
        )
    else:
        import uuid as _uuid
        from datetime import datetime, timezone

        markers = sa.table(
            "restore_markers",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("user_id", postgresql.UUID(as_uuid=True)),
            sa.column("label", sa.String),
            sa.column("kind", sa.String),
            sa.column("journal_seq", sa.BigInteger),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )
        user_ids = bind.execute(sa.text("SELECT id FROM users")).fetchall()
        if user_ids:
            op.bulk_insert(
                markers,
                [
                    {
                        "id": _uuid.uuid4(),
                        # SQLite hands ids back as hex strings;
                        # the UUID column wants real UUID objects.
                        "user_id": _uuid.UUID(str(row[0])),
                        "label": "Account created",
                        "kind": "baseline",
                        "journal_seq": 0,
                        # SQLite has no now() for the server
                        # default — stamp it here.
                        "created_at": datetime.now(timezone.utc),
                    }
                    for row in user_ids
                ],
            )


def downgrade() -> None:
    bind = op.get_bind()
    settings_table = sa.table(
        "system_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.JSON),
    )
    op.execute(
        settings_table.delete().where(
            settings_table.c.key == "audit.retention_days"
        )
    )
    op.drop_table("retained_files")
    op.drop_table("restore_markers")
    op.drop_table("change_journal")
    if bind.dialect.name == "postgresql":
        op.execute("DROP SEQUENCE IF EXISTS change_journal_seq")
