"""3D print files tables (owner order 2026-11-08, Downloads
Part 2).

The community shelf of free 3D print files for the shop:
registered members publish, everyone downloads the print files,
and the registered-only extras (STEP files, ratings, comments)
hang off the same records.

- PrintFile — one showcased file: its publisher, category (the
  prints module's OWN category set — categories.py, never the
  tool categories), the current version pointer, the public
  counters (print downloads across all versions, STEP downloads,
  the rating sum/count the average reads from), and the removal
  tombstone. Removal is a state, never a delete (the boards'
  moderation pattern): the record keeps who removed it and why,
  the shelf stops showing it, and downloads stop.
- PrintFileVersion — one uploaded version of a file. The print
  file is required; the STEP file is optional (Ryan's spec
  seats STEP on every listing that has one). Old versions stay
  listed and downloadable after an update — the version number
  only ever rises.
- PrintMedia — one showcase item on a LISTING (never on a
  version): a photo (up to five per listing) or the listing's
  one video (30 seconds max, its length verified at upload
  and stored here). One sort sequence orders photos and the
  video together — the Photos / Video tab's tile order and
  the preview viewer's walk order. The listing's first PHOTO
  in that order is its cover; PrintFile.preview_key /
  preview_content_type remain as the denormalized cover the
  shelf rows, search, and the header have always read, kept
  in step by the service on every media change.
- PrintRating — one member's stars for one file (1..5, one row
  per member per file, changeable). The file's rating_sum /
  rating_count are maintained in the same transaction so the
  average is exact, never recomputed from a scan.
- PrintComment — one comment on one file, forum posture:
  live | removed_author | removed_mod, with the account-
  deletion author_gone tombstone the forum posts carry.
- PrintReport — one flag of one file or one comment, feeding
  the shared moderation queue (the forum_reports shape):
  open | dismissed | actioned, one open report per member per
  target. file_id is denormalized onto comment reports so the
  queue groups without a join through a possibly-removed
  comment.
- PrintMakerLink — one outside maker-profile link a member
  keeps (MakerWorld, Printables, Thingiverse, …), shown on
  every file page they publish.

Storage keys only — bytes live in the storage service, the
Part 1 downloads discipline. The FK doctrine: user references
that are pure audit trail (removed_by_id, resolved_by_id) are
plain columns, like the forum's; live ownership references
(publisher, author, rater, reporter) are real FKs, and the
account-deletion cascade in core names every one of them.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PrintFile(Base):
    __tablename__ = "print_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    # Account-deletion tombstone (the forum posts' pattern): the
    # account is gone; the shelf renders "Former member" and the
    # cascade takes the file off the shelf in the same pass.
    publisher_gone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    # One of categories.CATEGORIES — validated in the service.
    category_key: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    # live | removed (FILE_STATUSES).
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="live", index=True
    )
    removed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    removed_reason: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    # Public counters — every print download, all versions.
    download_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    step_download_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # The rating aggregate: average = sum / count, exact.
    rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    preview_key: Mapped[str | None] = mapped_column(String(300))
    preview_content_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class PrintFileVersion(Base):
    __tablename__ = "print_file_versions"
    __table_args__ = (
        UniqueConstraint(
            "file_id", "version_number", name="uq_print_version_file_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("print_files.id"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    print_key: Mapped[str] = mapped_column(String(300), nullable=False)
    print_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    print_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The STEP file for this version, when the publisher
    # included one — registered members only at the read door.
    step_key: Mapped[str | None] = mapped_column(String(300))
    step_filename: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    step_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_downloads: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class PrintMedia(Base):
    """One showcase media item on a listing: a photo or the
    listing's one video. Media belongs to the LISTING
    (PrintFile), never to a version — the version flow is the
    print/STEP files' alone, and a listing edit (photos, text)
    never moves the version number."""

    __tablename__ = "print_media"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("print_files.id"),
        nullable=False,
        index=True,
    )
    # photo | video (MEDIA_KINDS in service.py).
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default=""
    )
    filename: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Videos only: the duration measured on the server from
    # the file's own bytes at upload (seconds). Null on photos.
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    # One order across photos and the video: the tab's tiles
    # and the viewer's walk read it; the first photo in it is
    # the listing's cover.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class PrintRating(Base):
    __tablename__ = "print_ratings"
    __table_args__ = (
        UniqueConstraint("file_id", "user_id", name="uq_print_rating_file_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("print_files.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class PrintComment(Base):
    __tablename__ = "print_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("print_files.id"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # live | removed_author | removed_mod (COMMENT_STATUSES).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="live"
    )
    removed_reason: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    author_gone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


REPORT_TARGET_KINDS = ("file", "comment")
REPORT_STATUSES = ("open", "dismissed", "actioned")


class PrintReport(Base):
    """One flag of one print file or one of its comments,
    feeding the shared moderation queue."""

    __tablename__ = "print_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # file | comment (REPORT_TARGET_KINDS).
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # The file the target hangs off (the file itself, or the
    # file the flagged comment sits on) — denormalized so the
    # queue can group + link without a join.
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("print_files.id"),
        nullable=False,
        index=True,
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # open | dismissed | actioned (REPORT_STATUSES).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open"
    )
    resolution: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class PrintFileFollow(Base):
    """One member's per-file update opt-in (sweep E4,
    busy-work #6, 2026-11-12): "tell me when THIS print file
    gets a new version." Presence IS the opt-in — the default
    is OFF (no row), following creates the row, unfollowing
    deletes it. The publisher never follows their own file
    through this door (the service refuses it), and the
    update fan-out excludes the publisher regardless."""

    __tablename__ = "print_file_follows"
    __table_args__ = (
        UniqueConstraint("user_id", "file_id", name="uq_print_file_follow"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("print_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class PrintMakerLink(Base):
    """One outside maker-profile link (MakerWorld, Printables,
    Thingiverse, …) a member keeps; shown on their file pages."""

    __tablename__ = "print_maker_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
