"""Disaster Vault (platform backups, owner spec 2026-10-18):
the backup_runs ledger.

One row per nightly bundle run, written by the backup service
(app/backup/job.py) when the run starts and completed with its
outcome, so a crashed job leaves a visible "running" row instead
of a silent gap. Carries the bundle name/size, whether it was
encrypted / uploaded / verified, a status (running | ok |
local_only | encryption_not_configured | failed), and a JSON
detail (manifest summary, failing stage + error, report emails
sent).

One new table; nothing existing is touched.

Downgrade drops the table.

Revision ID: 0013_backup_runs
Revises: 0012_email_flows
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_backup_runs"
down_revision: str | Sequence[str] | None = "0012_email_flows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bundle_name", sa.String(length=120), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uploaded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="running"),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backup_runs_started_at", "backup_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_backup_runs_started_at", table_name="backup_runs")
    op.drop_table("backup_runs")
