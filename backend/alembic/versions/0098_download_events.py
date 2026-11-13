"""0098: download_events — a dated record of every counted
download (dashboard-flare lane, owner order 2026-11-09).

The Downloads widget is to show the TOP DOWNLOADS THIS WEEK.
The shelf's only number is download_files.download_count — a
cumulative counter with no dates — so the honest version of
that widget needs the one record the system never kept: WHEN
each download happened. This migration adds exactly that and
nothing else: a new append-only table, one row per counted
download, written by downloads/service.record_download in the
same transaction as the counter increment from the moment
this ships.

Honesty boundary (recorded for whoever reads the widget):
events exist only from this migration forward. The weekly
ranking the widget shows is computed over the last 7 days of
EVENTS; while the record is younger than a week, the endpoint
says when tracking began and the widget labels the strip with
that truth ("since <date>") instead of claiming a full week
it cannot back. The cumulative counters are untouched and
keep meaning exactly what they always meant.

Table-level ops only — no model __table__ objects, no
hand-written SQL (the 0084/0089/0090/0096 posture). The
referenced table's shape (download_files: key varchar(64)
unique, created by 0092) was verified against a fresh
production schema dump taken for this lane. Downgrade drops
the table and its indexes — the counters it shadowed are
unaffected.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0098_download_events"
down_revision = "0097_feedback_for_downloads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "download_events",
        # No server default for the id: the app's model supplies
        # uuid4 Python-side on every insert (0092's posture), so
        # the DDL stays identical on every database.
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "file_key",
            sa.String(64),
            sa.ForeignKey("download_files.key"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_download_events_file_key", "download_events", ["file_key"]
    )
    op.create_index(
        "ix_download_events_created_at", "download_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_download_events_created_at", table_name="download_events")
    op.drop_index("ix_download_events_file_key", table_name="download_events")
    op.drop_table("download_events")
