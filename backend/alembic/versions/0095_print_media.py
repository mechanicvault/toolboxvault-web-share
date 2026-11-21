"""0095: showcase media for 3D print listings (owner orders
2026-11-08 21:31–23:44 CST — up to 5 photos + one 30-second
video per listing, and publisher listing edits).

One new table:

- print_media — one showcase item on a LISTING (print_files),
  never on a version: kind photo | video, the storage key +
  content type, the stored filename and byte size, the
  video's server-measured duration in seconds (videos only),
  and one sort_order that orders photos and the video in a
  single sequence — the Photos / Video tab's tile order and
  the preview viewer's walk order. The first photo in the
  order is the listing's cover.

BACKFILL: every listing that carries a preview today
(print_files.preview_key) gains that same picture as photo
#1 (sort_order 0) of its media set, pointing at the SAME
storage object — no bytes move, no listing loses its
picture. print_files.preview_key / preview_content_type stay
in place as the denormalized cover the shelf has always read
(the service keeps them in step with the media set from here
on), so this migration touches no existing column. The
backfill runs as plain SELECT/INSERT through the migration
connection (portable, no vendor SQL), each row's filename
recovered from its storage key's tail (the keys are written
as prints/<publisher>/<file>/preview-<name>).

Column names verified against the CURRENT production schema
immediately before shipping (the standing migration rule):
print_files(id uuid, preview_key varchar(300),
preview_content_type varchar(100), created_at / updated_at
timestamptz) — read from a fresh production pg_dump taken by
this lane (evidence: prints-showcase-media/prod-schema-
before.sql). Plain table creation from explicit definitions
— no model __table__ DDL (the 0084/0091/0092/0093 posture).
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0095_print_media"
down_revision = "0094_downloads_visitor_counter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "print_media",
        sa.Column("id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("content_type", sa.String(length=100), server_default="", nullable=False),
        sa.Column("filename", sa.String(length=200), server_default="", nullable=False),
        sa.Column("size_bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(["file_id"], ["print_files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_print_media_file_id", "print_media", ["file_id"])

    # Backfill: today's single preview becomes photo #1 of
    # the set, on the same storage object.
    bind = op.get_bind()
    previews = bind.execute(
        sa.text(
            "SELECT id, preview_key, preview_content_type, created_at, updated_at "
            "FROM print_files WHERE preview_key IS NOT NULL"
        )
    ).fetchall()
    media = sa.table(
        "print_media",
        sa.column("id", PG_UUID(as_uuid=True)),
        sa.column("file_id", PG_UUID(as_uuid=True)),
        sa.column("kind", sa.String()),
        sa.column("storage_key", sa.String()),
        sa.column("content_type", sa.String()),
        sa.column("filename", sa.String()),
        sa.column("size_bytes", sa.Integer()),
        sa.column("duration_seconds", sa.Float()),
        sa.column("sort_order", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    def as_datetime(value):
        # Postgres hands back datetimes; a text-backed store
        # hands back strings — the row keeps its own stamps
        # either way.
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    for file_id, key, content_type, created_at, updated_at in previews:
        filename = key.rsplit("preview-", 1)[-1] if "preview-" in key else ""
        bind.execute(
            media.insert().values(
                id=uuid.uuid4(),
                file_id=(
                    file_id
                    if isinstance(file_id, uuid.UUID)
                    else uuid.UUID(str(file_id))
                ),
                kind="photo",
                storage_key=key,
                content_type=content_type or "",
                filename=filename[:200],
                size_bytes=0,
                duration_seconds=None,
                sort_order=0,
                created_at=as_datetime(created_at),
                updated_at=as_datetime(updated_at),
            )
        )


def downgrade() -> None:
    # The media rows go with the table; the cover each listing
    # shows stays where it always lived (print_files.preview_*
    # was never moved), so a downgrade shows every picture
    # exactly as before this migration.
    op.drop_index("ix_print_media_file_id", table_name="print_media")
    op.drop_table("print_media")
