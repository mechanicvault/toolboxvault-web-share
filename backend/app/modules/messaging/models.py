"""Messaging module tables.

Owned exclusively by the messaging module. Other modules consume
messaging through service.py, never by importing these models.

The shape (community suite, owner decisions 2026-10-19):

- message_threads — one two-party conversation. The pair is stored
  SORTED (participant_low_id < participant_high_id) so "the thread
  between A and B about X" is one lookup. A thread may be anchored
  to a context (anchor_type "part" + the part's id + a title
  snapshot, so the header stays readable if the part is later
  edited or unpublished). status is the quarantine state:
  "request" (first contact, sitting in the recipient's Message
  requests until they accept — or reply, which accepts) or
  "accepted".
- messages — append-only. `seq` is the monotonic order (the
  journal/checkouts pattern: a real Postgres sequence in
  production, max+1 on SQLite) because one transaction shares one
  timestamp and read markers compare against it. `status` is the
  firewall state: sent (delivered), held (in the moderation hold —
  the recipient never sees it unless a moderator releases it),
  shadow (the recipient has blocked the sender — the sender sees
  it as sent, it simply never arrives), removed (was delivered,
  then wiped by a moderator — both sides see a tombstone, the
  body is gone), discarded (was held, a moderator threw it away —
  invisible to the recipient, a tombstone for the sender).
  `flags` records WHY the firewall touched it (link, blast,
  blocked_domain:<domain>, lure) so the moderation queue can say
  what it is looking at.
- message_thread_states — one row per (thread, participant): the
  read marker (last_read_seq) and `hidden` (a declined request —
  gone from that participant's lists; the sender is never told).
- user_blocks — silent, permanent until unblocked.
- message_reports — a participant's report of a thread, feeding
  the moderation queue (role ladder: moderator / community_admin
  / operator).

Messages are deliberately NOT in the audit-trail journal: they
are two-party communication, not one owner's restorable content —
the same reason borrowing rows are visibility-only, one step
further. Deleting an account deletes its threads outright (core's
deletion cascade enumerates these tables).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

THREAD_STATUSES = ("request", "accepted")
MESSAGE_STATUSES = ("sent", "held", "shadow", "removed", "discarded")
REPORT_STATUSES = ("open", "dismissed", "actioned")


class MessageThread(Base):
    __tablename__ = "message_threads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    participant_low_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    participant_high_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # Who opened the thread (the first sender). The OTHER party is
    # the one a "request" waits on.
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Anchor: "" = a plain conversation; "part" = about a Community
    # Parts listing (anchor_id = the part, anchor_title = the
    # part's title at open time).
    anchor_type: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    anchor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    anchor_title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # request | accepted (THREAD_STATUSES).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="request")
    # NOTE: no denormalized last-message preview lives here. The
    # two sides of a thread can legitimately see DIFFERENT newest
    # messages (a held or shadow send is invisible to the
    # recipient), so previews are computed per viewer at read time
    # (service._viewer_message_stats).

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("message_threads.id"),
        nullable=False,
        index=True,
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # sent | held | shadow | removed | discarded (MESSAGE_STATUSES).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="sent")
    # Firewall flags: ["link"], ["blast"], ["blocked_domain:bit.ly"],
    # ["lure"], combinations allowed. Empty = untouched.
    flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MessageThreadState(Base):
    """One participant's view state on one thread."""

    __tablename__ = "message_thread_states"
    __table_args__ = (
        UniqueConstraint("thread_id", "user_id", name="uq_thread_state_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("message_threads.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # Read marker: every message with seq <= this has been seen by
    # this participant (subject to the quarantine masking rule —
    # the sender of a pending request never sees the recipient's
    # marker).
    last_read_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Declined (or otherwise dismissed) — gone from this
    # participant's lists. The other side is never told.
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class UserBlock(Base):
    """A silent block: the blocked party's messages never arrive
    and their new threads land as shadow threads only they can
    see. Permanent until the blocker removes it."""

    __tablename__ = "user_blocks"
    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_block_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    blocker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MessageReport(Base):
    """One report of one thread, feeding the moderation queue."""

    __tablename__ = "message_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("message_threads.id"),
        nullable=False,
        index=True,
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # open | dismissed | actioned (REPORT_STATUSES).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolution: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


from sqlalchemy import event, text  # noqa: E402  (hook lives with its model)


@event.listens_for(Message, "before_insert")
def _assign_message_seq(mapper, connection, target):  # noqa: ANN001, ANN202
    """Give every message the next sequence value — the journal
    pattern (migration 0027): Postgres draws from the real
    `message_seq` sequence (created by migration 0028); SQLite
    takes max+1 inside the insert transaction."""
    if target.seq is not None:
        return
    if connection.dialect.name == "postgresql":
        target.seq = connection.scalar(text("SELECT nextval('message_seq')"))
    else:
        target.seq = connection.scalar(
            text("SELECT COALESCE(MAX(seq), 0) + 1 FROM messages")
        )
