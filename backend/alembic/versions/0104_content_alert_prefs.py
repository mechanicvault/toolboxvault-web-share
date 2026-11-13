"""Content-alert opt-ins (sweep E4, busy-work #6).

Three new tables behind the notifications lane:

- `new_content_alert_prefs` (core/models.py NewContentAlertPref):
  one row per user who has touched the new-content boxes —
  `downloads_enabled` / `prints_enabled`, both default FALSE
  (Ryan's spec: every opt-in defaults OFF; absence of a row
  also reads OFF).
- `content_alert_state` (core/models.py ContentAlertState):
  the key/value watermark store; the downloads catalog sync
  stamps "downloads_catalog_seen_at" on its first-ever run so
  only catalog keys first appearing AFTER that baseline can
  ever notify.
- `print_file_follows` (prints/models.py PrintFileFollow):
  the per-print-file update opt-in; presence of a
  (user_id, file_id) row IS the opt-in.

Bare-safe by construction (the standing migration gate): this
file imports alembic + sqlalchemy only and names its tables
and columns literally. Columns verified against the models
that own them: core/models.py (NewContentAlertPref,
ContentAlertState) and prints/models.py (PrintFileFollow);
the flyer_alert_prefs table (flyers/models.py, migration
0081) is the shape precedent.

⚠ COORDINATOR GATE (flagged by lane E4 before any push): this
migration has NOT had the production-schema rehearsal. Before
pushing: (1) verify the final text below against the live
schema, (2) bare-subprocess upgrade + downgrade importing ONLY
this file (lane ran it — see the lane INDEX), (3) rehearsal
on a throwaway DB built from the current production schema.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0104_content_alert_prefs"
down_revision = "0103_health_photo_ignored"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "new_content_alert_prefs",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "downloads_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "prints_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "content_alert_state",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column(
            "value", sa.String(length=200), nullable=False, server_default=""
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "print_file_follows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("print_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "file_id", name="uq_print_file_follow"),
    )
    op.create_index(
        "ix_print_file_follows_user_id", "print_file_follows", ["user_id"]
    )
    op.create_index(
        "ix_print_file_follows_file_id", "print_file_follows", ["file_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_print_file_follows_file_id", table_name="print_file_follows")
    op.drop_index("ix_print_file_follows_user_id", table_name="print_file_follows")
    op.drop_table("print_file_follows")
    op.drop_table("content_alert_state")
    op.drop_table("new_content_alert_prefs")
