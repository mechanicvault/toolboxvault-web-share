"""0102: announcement per-language parts (single-language
rule, owner order 2026-11-10, broadened same day).

Nothing user-facing appears in a language other than the
user's own choice — email, inbox announcements, every surface.
Operator-composed feature announcements broke that everywhere:
the one stored body was composed EN + "\\n\\n" + ES and the
fan-out handed that stacked body to every recipient's inbox
(and to the email twin of anyone who opted in).

The stored title/body remain the English rendering (the Admin
history's record). This migration gives the row somewhere to
keep the per-language parts the fan-out renders each
recipient's copy from:

- title_es VARCHAR(200) NULL — the Spanish title.
- body_en  VARCHAR(1000) NULL — the English body on its own.
- body_es  VARCHAR(1000) NULL — the Spanish body on its own.

NULL on all three (every row that exists today, every module-
release row, every single-language compose) = the fan-out
falls back to the stored title/body for a recipient whose
locale has no composed part: one language, never a pair.

Column definitions mirror core/models.py FeatureAnnouncement,
written against the feature_announcements table as created by
0091 and extended by 0096 (title VARCHAR(200), body
VARCHAR(1000)). Explicit literal DDL only — no model __table__
objects, no hand-written SQL (the 0084/0096/0101 posture).
Bare-safe: this file imports alembic + sqlalchemy only.
"""

import sqlalchemy as sa
from alembic import op

revision = "0102_announcement_locale_parts"
down_revision = "0101_conversion_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feature_announcements",
        sa.Column("title_es", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "feature_announcements",
        sa.Column("body_en", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "feature_announcements",
        sa.Column("body_es", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("feature_announcements", "body_es")
    op.drop_column("feature_announcements", "body_en")
    op.drop_column("feature_announcements", "title_es")
