"""Community Forum tables (forum module).

Owned exclusively by the forum module. Other modules consume the
forum through service.py, never by importing these models.

Four tables:

- forum_categories — the operator's rooms. Seeded by migration
  0034 with the mechanic-first starter set; operators rename /
  reorder / archive them (archive is a flag, never a delete, so
  thread history is never orphaned). No owner: categories are
  platform furniture, not user content.

  `system_key` (migration 0070) marks the BUILT-IN rooms the
  system itself seeds: "site_help" (the dedicated using-Toolbox-
  Vault help room the Help & Support page's community tab
  embeds), "bug_reports" and "feature_requests" (the two
  PERMANENT boards, owner directive 2026-11-02: the Bug Reports
  and Feature Requests boards are permanent fixtures of the
  forum — the boards themselves can never be deleted or edited
  by anyone, operator path included; the lock is enforced in
  service.update_category). The two boards' POSTS stay powered
  by the feedback module (its statuses, votes, comments and the
  roadmap tie-in are the boards' approved mechanics); the forum
  category row is their permanent home in the board list, and
  serialize_category reports the boards' live feedback counts
  to member audiences (anonymous audiences get the rows with no
  counts or latest-post data — the boards are members-only
  reading since 2026-11-10).
  Individual posts inside the boards are ordinary posts —
  permanence belongs to the boards only.

- forum_threads — one discussion. The title lives here; the
  opening post is the first forum_posts row. `pinned` /
  `locked` are the moderator levers (pin sorts first in the
  category; locked refuses new replies). `last_post_at` /
  `last_post_id` drive category + thread ordering.

- forum_posts — one post (the opener or a reply). Replies are
  FLAT and chronological (build choice, 2026-10-20): a reply may
  carry a quote of ONE earlier post in the same thread —
  `quote_post_id` + the quoted author's name and an excerpt are
  SNAPSHOTTED onto the reply, so the quote survives the original
  being edited, removed, or its author leaving. `status` is the
  visibility state machine:
    visible        — everyone reads it
    held           — the spam firewall held it at post time; the
                     author and moderators see it, nobody else
                     does, until a moderator releases (visible)
                     or discards (removed_mod)
    removed_author — the author deleted it: a tombstone keeps the
                     thread's shape ("removed by the author")
    removed_mod    — a moderator removed it: tombstone with the
                     moderator-facing reason kept on the row
  `author_gone` marks the account-deletion tombstone: the account
  is gone, the body is wiped, the author renders as
  "Former member" — the thread itself must not break (the
  ratings rule from the marketplace build, applied to posts).
  A post may attach ONE community reference (`link_type` =
  "part" | "listing", `link_id`, title snapshotted) — validated
  live at post time through the owning module's service
  interface; the card resolves live at read time and degrades to
  an honest "no longer available" card, never a dangling id.

- forum_reports — a member's report of one post, feeding the
  moderation queue (the message_reports shape). One open report
  per (post, reporter).

- forum_favorites — one member's starred conversation (widget
  options Wave 3, owner design 2026-11-02, Decision 2: favorites
  built as a real forum feature). A favorite points at either a
  forum thread (kind "thread") or a PERMANENT board's post
  (kind "post" — the boards' posts are feedback rows, so the
  target id is a plain polymorphic column, no FK, the forum
  doctrine for cross-references). Favorites are PRIVATE: no
  counts, no public display, nobody else's list ever shows them.
  Reads resolve the target LIVE and silently drop what the
  member can no longer see (deleted, held for others, board
  switched off) — the row stays, the door just closes, exactly
  like a post's link card degrading.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

POST_STATUSES = ("visible", "held", "removed_author", "removed_mod")
LINK_TYPES = ("part", "listing")


def _utcnow() -> datetime:
    """Python-side clock for row timestamps: a flat thread's
    reading order must be insertion-true even when two posts land
    inside one database-clock tick (a server now() can tie at
    second precision), so created_at carries microsecond truth
    from the app. The server default stays for raw inserts."""
    return datetime.now(timezone.utc)
REPORT_STATUSES = ("open", "dismissed", "actioned")


class ForumCategory(Base):
    __tablename__ = "forum_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Built-in rooms carry a system key (migration 0070):
    # "site_help" | "bug_reports" | "feature_requests"; operator
    # rooms carry NULL. The two boards are PERMANENT (see the
    # module docstring); the key is also how the Help & Support
    # page finds its rooms without hard-coding an id.
    system_key: Mapped[str | None] = mapped_column(
        String(40), nullable=True, unique=True
    )
    # Display + listing order (operator-controlled).
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Archived categories hide from the list and refuse new
    # threads; their history stays readable.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class ForumThread(Base):
    __tablename__ = "forum_threads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("forum_categories.id"),
        nullable=False,
        index=True,
    )
    # PLAIN column (no FK) by design: the thread survives its
    # author's account deletion as a "Former member" tombstone
    # (the marketplace two-party-history doctrine).
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The opening post was held by the firewall: the thread exists
    # for its author + moderators but is invisible to everyone
    # else until the opener is released (then it clears).
    held: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    # Account-deletion tombstone for the opener's identity (the
    # thread + its replies survive; the author renders as
    # "Former member").
    author_gone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    last_post_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    last_post_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class ForumPost(Base):
    __tablename__ = "forum_posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("forum_threads.id"),
        nullable=False,
        index=True,
    )
    # PLAIN column (no FK) — see ForumThread.author_id.
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # visible | held | removed_author | removed_mod (POST_STATUSES).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="visible", index=True
    )
    # Why a moderator removed it (moderator/audit-facing; the
    # public tombstone carries no detail).
    removed_reason: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    # The firewall's flags at post time ("link", "lure",
    # "blocked_domain:<d>") — a JSON list stored as text so the
    # queue can show what the screen saw.
    flags: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Quote snapshot (flat replies with quotes — see docstring).
    quote_post_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    quote_author_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    quote_excerpt: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    # The ONE community reference a post may attach (validated
    # live at post time; the title is the snapshot the dead-ref
    # card falls back to).
    link_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    link_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    link_title: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Account-deletion tombstone (body wiped by the cascade).
    author_gone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class ForumReport(Base):
    """One report of one post, feeding the moderation queue."""

    __tablename__ = "forum_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("forum_posts.id"),
        nullable=False,
        index=True,
    )
    # Denormalized so the queue can group + link without a join
    # through a possibly-tombstoned post.
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("forum_threads.id"),
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
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


FAVORITE_KINDS = ("thread", "post")


class ForumFavorite(Base):
    """One member's starred conversation — a forum thread or a
    permanent board's feedback post. Private to the member: the
    list endpoint is the only reader and it only ever answers
    the owner's own rows. One favorite per (member, target):
    starring twice is the same star."""

    __tablename__ = "forum_favorites"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "kind", "target_id", name="uq_forum_favorite_user_target"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # "thread" (forum_threads.id) | "post" (feedback_posts.id) —
    # FAVORITE_KINDS. A plain column, no FK: the target lives in
    # one of two tables, and a favorite must survive its target
    # being deleted (the read just stops resolving it).
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


# Community features a member can be blocked from, one at a time
# (community moderation, owner ruling 2026-11-06): the forums and
# the Bug/Feature boards are enforceable today; Community Parts
# is a RESERVED key — the parts module is parked (its code and
# data are untouchable), and the machinery carries the key so
# the parts surfaces adopt blocks the day the module unparks,
# with no redesign. The 3D print files (print_files) joined as a
# live key with the Downloads Part 2 lane (2026-11-08) — its
# upload and comment doors enforce blocks like the forums'. The
# marketplace is deliberately NOT a community block feature:
# selling carries its own reputation + operator machinery.
COMMUNITY_FEATURES = ("forums", "feedback_boards", "community_parts", "print_files")

FEATURE_LABELS = {
    "forums": "the community forums",
    "feedback_boards": "the Bug Reports and Feature Requests boards",
    "community_parts": "Community Parts",
    "print_files": "the 3D print files",
}


class CommunityBlock(Base):
    """One member's block from ONE community feature (admin
    lane, owner ruling 2026-11-06; migration 0085).

    This is NOT the platform ban (banned_emails + deactivation —
    the moderation queue's sledgehammer, messaging.ban_user):
    a block is per-feature and surgical. The blocked member
    keeps their account, their inventory, everything else —
    they simply cannot post or reply in the blocked feature
    (enforced server-side at the write doors), and they are
    told, in their inbox, which feature and that a support
    ticket can ask for reinstatement.

    Only god + moderator_admin seats impose or lift a block
    (the service + route gates); moderators see the list and
    work the flag queue, but the block itself is an admin act.
    A block is lifted, never deleted: lifted_at / lifted_by_id
    close the row and the history stays. One ACTIVE block per
    (member, feature) — the partial unique index is the backstop
    for the service's own check."""

    __tablename__ = "community_blocks"
    __table_args__ = (
        Index(
            "uq_community_block_active",
            "user_id",
            "feature",
            unique=True,
            postgresql_where=text("lifted_at IS NULL"),
            sqlite_where=text("lifted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # One of COMMUNITY_FEATURES.
    feature: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # PLAIN columns (the forum doctrine): the audit trail keeps
    # the actors' ids even if an account later goes away; names
    # resolve live at read time.
    blocked_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    lifted_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
