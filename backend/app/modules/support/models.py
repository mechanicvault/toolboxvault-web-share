"""Support ticket tables (support module, 2026-10-24).

The Help & Support page's ticket system: a signed-in member opens
a ticket, trades messages with the support team (operators), and
the ticket moves through a small lifecycle:

  - open        — waiting on the team (a fresh ticket, or the
                  member replied while it was under review).
  - under_review — the team has it in hand (an operator reply
                  lands a ticket here automatically).
  - closed      — done; no more replies from the member side.

(Owner steer 2026-10-24: exactly these three statuses. The
shipped "answered" became "under_review" — migration 0053
rewrites existing rows.)

Two tables:

- support_tickets — one conversation thread: owner (user_id, a
  real FK with CASCADE — a ticket is private two-party mail, not
  public content, so it dies with the account), subject, status.
- support_messages — the messages inside a ticket, oldest first.
  author_id is a real FK too (CASCADE); author_kind records which
  side of the desk wrote it ("user" | "operator") so the thread
  renders correctly without joining anything.

- help_videos — the How-to videos tab's list (migration 0070,
  Help & Support build 2026-11-02): operator-managed entries,
  each a title, one line about what it teaches, the YouTube
  video id (videos live on the Toolbox Vault YouTube channel
  and play in place — no video files are hosted here), the
  side it belongs to ("website" | "app"), a display order and
  a published flag. Unpublished rows are operator drafts; the
  member face only ever sees published ones. No owner: like
  forum categories, these are platform furniture.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

STATUSES = ("open", "under_review", "closed")
AUTHOR_KINDS = ("user", "operator")
VIDEO_SECTIONS = ("website", "app")


def _utcnow() -> datetime:
    """Python-side clock (the feedback rule): message order must
    be insertion-true even inside one database-clock tick."""
    return datetime.now(timezone.utc)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    # open | under_review | closed (STATUSES)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # user | operator (AUTHOR_KINDS)
    author_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class HelpVideo(Base):
    __tablename__ = "help_videos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # One line about what the walkthrough teaches.
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The YouTube video id only (the service extracts it from
    # whatever the operator pastes — a watch URL, a short link,
    # or the bare id — and validates the shape).
    youtube_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # website | app (VIDEO_SECTIONS)
    section: Mapped[str] = mapped_column(
        String(10), nullable=False, default="website", index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Drafts (False) are operator-only; the member face lists
    # published rows only.
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
