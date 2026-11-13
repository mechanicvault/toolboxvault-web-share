"""Feedback boards tables (feedback module, wave 3, 2026-10-20).

Two PUBLIC boards — Bug Reports and Feature Requests — under one
module: a post names its board; the board is a filter, not a
second table set, so status vocabulary, votes, comments and
moderation are written once.

DELIBERATE DEVIATION (owner decision 2026-10-20): the community
forum gates POSTING behind a paid plan; feedback does not. Ryan
ruled feedback open to members — ANY signed-in account, free
included, may post, vote and comment. Reading was public until
2026-11-10 (busy work #1): the boards are members-only reading
now, refused to anonymous callers server-side on both read
faces (exact-key payloads, no emails, for members). The spam
firewall + trust budgets still apply to every write.

Four tables:

- feedback_posts — one bug report or feature request: board,
  title, body, lifecycle status (open | acknowledged | planned |
  in_progress | done | declined — set by moderators / operators /
  community_admins, with an optional public status note), the
  filer's urgency (low | medium | high — migration 0084; set at
  filing, editable afterwards by moderators only), and the
  forum-style visibility state (visible | held | removed_author |
  removed_mod) driven by the spam firewall and moderation.
  author_id is a PLAIN column (no FK — the forum doctrine): the
  post survives its author's account deletion as a "Former
  member" tombstone.
- feedback_votes — one upvote per (post, user); a toggle, never a
  counter stored on the post.
- feedback_comments — FLAT comments under a post (the forum's
  reply shape), same visibility state machine.
- feedback_reports — one member's report of one post or comment,
  feeding the Moderation page's Feedback section. One OPEN report
  per (target, reporter), enforced in the service.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

BOARDS = ("bug", "feature")
URGENCIES = ("low", "medium", "high")
STATUSES = ("open", "acknowledged", "planned", "in_progress", "done", "declined")
# Closure (sweep E5, busy-work #7, 2026-11-12): a post is CLOSED
# exactly when its status is a decision — done or declined. The
# closed state is DERIVED from status (never a stored flag), so
# there is one source of truth: marking done/declined closes the
# post in the same action, and moving it back to an active status
# reopens it in the same action, with no second write to drift.
CLOSED_STATUSES = ("done", "declined")


def is_closed(status: str) -> bool:
    """The one closure test every read surface shares."""
    return status in CLOSED_STATUSES
VISIBILITIES = ("visible", "held", "removed_author", "removed_mod")
REPORT_STATUSES = ("open", "dismissed", "actioned")
TARGET_KINDS = ("post", "comment")


def _utcnow() -> datetime:
    """Python-side clock (the forum's rule): flat comment order
    must be insertion-true even inside one database-clock tick."""
    return datetime.now(timezone.utc)


class FeedbackPost(Base):
    __tablename__ = "feedback_posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # bug | feature (BOARDS)
    board: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # PLAIN column (no FK) by design: the post survives its
    # author's account deletion as a "Former member" tombstone.
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The lifecycle status the roadmap shows (STATUSES) — set by
    # moderators/operators/community_admins only.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )
    # The moderator's optional public note riding the status
    # ("Fixed in the next update", "Needs more detail", …).
    status_note: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    # The filer's urgency call (migration 0084, owner
    # 2026-11-06): low | medium | high (URGENCIES), picked on
    # the 3-position toggle at filing time, default medium.
    # The filer can never change it afterwards; moderators /
    # operators / community_admins can (service.set_urgency).
    urgency: Mapped[str] = mapped_column(
        String(10), nullable=False, default="medium", server_default="medium"
    )
    # Visibility state machine (VISIBILITIES): the spam firewall
    # holds; moderators remove; authors remove their own.
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="visible", index=True
    )
    removed_reason: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    # The firewall's flags at post time ("link", "lure", …), JSON
    # as text, like the forum's.
    flags: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Account-deletion tombstone: body wiped, author renders as
    # "Former member".
    author_gone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class FeedbackVote(Base):
    __tablename__ = "feedback_votes"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_feedback_vote_post_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feedback_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # PLAIN column: a vote outlives nothing — the cascade sweeps
    # the voter's rows — but the two-party posture keeps the table
    # uniform with its siblings.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class FeedbackComment(Base):
    __tablename__ = "feedback_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feedback_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # PLAIN column (tombstone doctrine, as posts).
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # visible | held | removed_author | removed_mod
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="visible", index=True
    )
    removed_reason: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    flags: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_gone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class FeedbackReport(Base):
    """One report of one post or comment, feeding the moderation
    queue's Feedback section."""

    __tablename__ = "feedback_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # post | comment (TARGET_KINDS)
    target_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # open | dismissed | actioned (REPORT_STATUSES)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )
    resolution_note: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
