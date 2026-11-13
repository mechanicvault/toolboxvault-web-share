"""0092: the downloads documents catalog (owner order
2026-11-08 — the /downloads bare door becomes a real page with
a Documents tab).

One new table:

- download_files — one row per file on the Documents shelf:
  its stable key, format, the friendly filename the browser
  saves, the storage key carrying its bytes, its shelf order,
  and the public download counter the list shows. Seeded here
  with the nine files of the opening shelf (the definitions
  live in app/modules/downloads/catalog.py; the service upserts
  from the same list, so a later shelf addition needs no data
  migration). Row ids are uuid5 of the key — stable across
  rehearsals, referenced by nothing.

Plain table creation + seed from explicit definitions — no
model __table__ DDL and no hand-written SQL beyond the seed
inserts (the 0084/0091 posture). Verified against the live
production schema immediately before shipping: production at
0091 (this migration's down_revision), no download_files table
present (information_schema count 0).
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0092_download_files"
down_revision = "0091_feature_announcements"
branch_labels = None
depends_on = None

# (key, format, saved-as filename, storage key, sort order) —
# mirrors app/modules/downloads/catalog.py exactly.
_SEED = [
    ("tool-inventory", "xlsx", "Toolbox-Vault-Tool-Inventory.xlsx", "downloads/tool-inventory.xlsx", 10),
    ("paycheck-calculator", "xlsx", "Mechanic-Paycheck-Overtime-Calculator.xlsx", "downloads/paycheck-overtime-calculator.xlsx", 20),
    ("flat-rate-tracker", "xlsx", "Flat-Rate-Hours-Tracker.xlsx", "downloads/flat-rate-hours-tracker.xlsx", 30),
    ("inspection-checklist", "pdf", "Vehicle-Inspection-Checklist.pdf", "downloads/vehicle-inspection-checklist.pdf", 40),
    ("pre-purchase-form", "pdf", "Pre-Purchase-Vehicle-Inspection-Form.pdf", "downloads/pre-purchase-inspection-form.pdf", 50),
    ("diagnostic-worksheet", "pdf", "Diagnostic-Worksheet.pdf", "downloads/diagnostic-worksheet.pdf", 60),
    ("electrical-worksheet", "pdf", "Electrical-Diagnostic-Worksheet.pdf", "downloads/electrical-diagnostic-worksheet.pdf", 70),
    ("intake-form", "pdf", "Customer-Vehicle-Intake-Form.pdf", "downloads/customer-vehicle-intake-form.pdf", 80),
    ("torque-chart", "pdf", "Torque-Conversion-Chart.pdf", "downloads/torque-conversion-chart.pdf", 90),
]


def _row_id(key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"toolboxvault/downloads/{key}")


def upgrade() -> None:
    table = op.create_table(
        "download_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("file_format", sa.String(length=8), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("download_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_download_files_key", "download_files", ["key"])
    op.bulk_insert(
        table,
        [
            {
                "id": _row_id(key),
                "key": key,
                "file_format": file_format,
                "filename": filename,
                "storage_key": storage_key,
                "sort_order": sort_order,
                "is_active": True,
                "download_count": 0,
            }
            for key, file_format, filename, storage_key, sort_order in _SEED
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_download_files_key", table_name="download_files")
    op.drop_table("download_files")
