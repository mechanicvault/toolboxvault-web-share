"""Wave 4 (2026-10-20): community catalog, UPC, cloud backups.

Four changes, one migration:

- tools.upc + batteries.upc — the barcode/UPC the item carries
  (Quick Add + the layered lookup chain key off it; duplicate
  detection treats a shared UPC as an identity signal). Plain
  string, default "" — most items have none recorded.
- users.catalog_contribute — the community-catalog consent
  switch (Settings -> Sharing). DEFAULT TRUE with explicit copy
  naming the fields that contribute (brand/model/category/size/
  list price) and the ones that NEVER do (serials, prices paid,
  photos, notes). Aggregation reads live items at request time,
  so flipping this off removes the user's weight immediately —
  there are no contribution copies to scrub.
- cloud_drive_connections + cloud_backup_runs — the user's own
  Google Drive auto-backup: ONE connection row per user (the
  refresh token lives there, encrypted at rest — see
  app/modules/core/cloud_backup.py) and the backup history
  ledger. BOTH user columns are PLAIN ids (no FK — the 0038
  lesson); the core deletion cascade sweeps them explicitly.

The community catalog itself needs NO table: it is derived from
tools + batteries at read time (app/modules/catalog/service.py).

Revision ID: 0042_wave4
Revises: 0041_wave3
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_wave4"
down_revision: str | None = "0041_wave3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)

_NOW = sa.func.now()


def upgrade() -> None:
    # -- UPC on both asset kinds ------------------------------------
    op.add_column(
        "tools",
        sa.Column("upc", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "batteries",
        sa.Column("upc", sa.String(64), nullable=False, server_default=""),
    )

    # -- community catalog consent -----------------------------------
    op.add_column(
        "users",
        sa.Column(
            "catalog_contribute",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # -- cloud (Google Drive) user auto-backups -----------------------
    op.create_table(
        "cloud_drive_connections",
        sa.Column("id", _UUID, primary_key=True),
        # PLAIN column on purpose — see the module docstring; the
        # core deletion cascade sweeps these rows explicitly.
        sa.Column("user_id", _UUID, nullable=False),
        # The OAuth refresh token, Fernet-encrypted at rest (never
        # plaintext, never serialized out of the API).
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("drive_folder_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("drive_folder_name", sa.String(200), nullable=False, server_default=""),
        # off | daily | weekly — the jobs scheduler executes what's due.
        sa.Column("schedule", sa.String(10), nullable=False, server_default="off"),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_backup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index(
        "ix_cloud_drive_connections_user_id",
        "cloud_drive_connections",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "cloud_backup_runs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("user_id", _UUID, nullable=False),
        # manual | scheduled
        sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
        # running | ok | failed
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("file_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("file_name", sa.String(300), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_cloud_backup_runs_user_id", "cloud_backup_runs", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_cloud_backup_runs_user_id", table_name="cloud_backup_runs")
    op.drop_table("cloud_backup_runs")
    op.drop_index(
        "ix_cloud_drive_connections_user_id", table_name="cloud_drive_connections"
    )
    op.drop_table("cloud_drive_connections")
    op.drop_column("users", "catalog_contribute")
    op.drop_column("batteries", "upc")
    op.drop_column("tools", "upc")
