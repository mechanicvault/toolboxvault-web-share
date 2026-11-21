"""Background jobs ledger (step-4 fix round, 2026-10-20).

One new table, core-owned:

- job_runs — one row per run of a periodic background job,
  written by the compose `jobs` service (app/scripts/scheduler.py)
  in the BackupRun shape: a row opens as "running" and completes
  with status ok|failed plus the job's summary (or the error) in
  `detail`. Admin → Settings reads the latest run per job from
  here. Until this build the five run_*_jobs scripts had NO
  scheduler at all — lapse transitions, AI refills, maintenance /
  claims notifications, the marketplace 14-day publication sweep
  and the audit daily markers + tombstone purge simply never ran
  in production.

Revision ID: 0035_job_runs
Revises: 0034_forum
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_job_runs"
down_revision: str | None = "0034_forum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job", sa.String(length=40), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="running"
        ),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_runs_job", "job_runs", ["job"])
    op.create_index("ix_job_runs_started_at", "job_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_started_at", table_name="job_runs")
    op.drop_index("ix_job_runs_job", table_name="job_runs")
    op.drop_table("job_runs")
