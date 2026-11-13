"""Downloads module tables — the public lead-magnet subscriber list.

One row per email address that asked for Toolbox Vault updates on
the /downloads page. This is NOT an account and NOT a billing
subscription: just an address, where it came from, and the
unsubscribe token every update email will carry. Unsubscribing
stamps `unsubscribed_at` (the row stays — CAN-SPAM record-keeping);
subscribing again clears the stamp.

DownloadFile (2026-11-08): one row per file on the downloads
page's Documents shelf — the catalog's durable half (the file
definitions live in catalog.py; the bytes live in the storage
service, seeded from the packaged files). `download_count` is
the public counter the list shows: every download, signed-in or
not, moves it by one, in the same request that serves the file.

DownloadEvent (2026-11-09, dashboard-flare lane): one row per
counted download, stamped when it happens — the dated record
the cumulative counter never kept, so "top downloads this
week" can be TRUE instead of a relabelled all-time list. The
counter stays the public number; events only feed the weekly
ranking. Written by service.record_download in the same
transaction as the increment — the two can never disagree
about whether a download happened.
"""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _new_token() -> str:
    return secrets.token_urlsafe(32)


class DownloadsSubscriber(Base):
    __tablename__ = "downloads_subscribers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="downloads"
    )
    unsubscribe_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True, default=_new_token
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    unsubscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DownloadFile(Base):
    __tablename__ = "download_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    file_format: Mapped[str] = mapped_column(String(8), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    download_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DownloadEvent(Base):
    """One counted download, dated (see the module docstring).
    `file_key` is the DownloadFile key the download moved —
    a document's own key, or a wallpaper's per-size key
    (`<artwork>-<size>`), exactly as record_download received
    it; the weekly aggregation folds size keys back onto their
    artwork."""

    __tablename__ = "download_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("download_files.key"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
