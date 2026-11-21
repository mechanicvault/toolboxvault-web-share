"""General importer (2026-10-19): import sessions.

One table — import_sessions. An uploaded spreadsheet's raw bytes
live server-side against an owner-scoped session (24h expiry) so
the mapping / dry-run / confirm flow never needs a re-upload.
Confirming consumes the session; account deletion removes them.

Revision ID: 0019_import_sessions
Revises: 0018_reports
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_import_sessions"
down_revision: str | None = "0018_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="tool"),
        sa.Column("filename", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "file_format", sa.String(length=10), nullable=False, server_default="csv"
        ),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "headers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_import_sessions_owner_id"), "import_sessions", ["owner_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_import_sessions_owner_id"), table_name="import_sessions")
    op.drop_table("import_sessions")
