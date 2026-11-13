"""Health-check photo ignore flag (sweep E3, busy-work #5).

Adds `health_photo_ignored` (boolean, NOT NULL, default false)
to `tools` and `batteries`: the owner's per-item, photo-only,
reversible opt-out from the Health Check's missing-photo flag.
The readiness scan (inventory service.health_check) and every
consumer of its verdict (the Health checks due widget read, the
claim-readiness nudges) honor the flag; no other gap reads it.

Bare-safe by construction (the standing migration gate): this
file imports alembic + sqlalchemy only and names its tables and
columns literally. Columns verified against the models that own
them: tools / batteries — inventory/models.py Tool / Battery
(business_use, added the same way, is the pattern column:
Boolean, nullable=False, server_default "false").

⚠ COORDINATOR GATE (flagged by lane E3 before any push): this
migration has NOT had the production-schema rehearsal. Before
pushing: (1) verify the final text below against the live schema
(\\d tools / \\d batteries on production), (2) bare-subprocess
upgrade + downgrade importing ONLY this file, (3) rehearsal on a
throwaway DB built from the current production schema.
"""

import sqlalchemy as sa
from alembic import op

revision = "0103_health_photo_ignored"
down_revision = "0102_announcement_locale_parts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tools",
        sa.Column(
            "health_photo_ignored",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "batteries",
        sa.Column(
            "health_photo_ignored",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("batteries", "health_photo_ignored")
    op.drop_column("tools", "health_photo_ignored")
