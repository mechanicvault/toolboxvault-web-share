"""Tools For Sale + reputation tables (marketplace module).

Owned exclusively by the marketplace module. Other modules consume
marketplace through service.py / reputation.py, never by importing
these models (messaging's one exception-by-design: it validates
"listing" anchors through marketplace's service interface).

Four tables:

- sale_listings — one for-sale / wanted listing. A listing is a
  SNAPSHOT: created from an inventory item it copies the display
  facts (title, brand, model) and COPIES the photo objects into
  the marketplace namespace, so later inventory edits — or the
  item's deletion — never silently rewrite (or strip the photos
  from) a live listing. The seller edits the listing itself.
  `source_kind` / `source_id` are provenance only: plain columns,
  no FK, never read back into a payload beyond the owner's view.

- deal_interactions — one COMPLETED deal between two people: the
  only thing that can be rated (community suite: no interaction
  record = no rating, anti-gaming). Created when a listing is
  marked sold WITH a buyer identified, or when both sides of an
  anchored messaging thread close it as completed. The party ids
  are PLAIN columns (no FK) with name snapshots, on purpose: an
  interaction is two-party history (the borrowing-ledger shape),
  and it must survive either account's deletion so the OTHER
  party's completed-deals count and published ratings stay honest.

- ratings — one per side per interaction (unique constraint),
  1–5 stars + short text, DOUBLE-BLIND: `published_at` stays NULL
  while a rating is private. Both submitted → both publish
  together; 14 days after the interaction completed, a lone
  rating publishes anyway (silence is not a veto — owner decision
  2026-10-19). rater/ratee ids are plain columns: when a rater's
  account is deleted the stars keep counting toward the ratee's
  aggregate and the display name resolves to "Former member".

- thread_completions — one row per (anchored thread, participant)
  who closed the conversation as a completed deal. The lightest
  consistent home for the both-sides rule: messaging owns threads
  and deliberately keeps no deal state; the second row landing is
  what creates the interaction.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

LISTING_TYPES = ("for_sale", "wanted")
LISTING_STATUSES = ("active", "sold", "removed")
INTERACTION_SOURCES = ("listing", "part", "thread")


class SaleListing(Base):
    __tablename__ = "sale_listings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # for_sale | wanted (LISTING_TYPES).
    listing_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="for_sale"
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # NULL price = "Make offer".
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # The LISTING's own condition vocabulary — deliberately NOT
    # inventory's (Package B removed condition from inventory;
    # listings keep their own free text and it never flows back).
    condition: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    brand: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    delivery_local_pickup: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    delivery_ships: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Per-listing overrides (NULL = inherit the profile):
    # - public_area_label overrides the profile's coarse area.
    # - show_phone_override beats the profile's show_phone toggle.
    public_area_label: Mapped[str | None] = mapped_column(String(120))
    show_phone_override: Mapped[bool | None] = mapped_column(Boolean)
    # Provenance only: what inventory record this listing was
    # created from ("" = standalone). Plain columns — the listing
    # must not depend on the record's survival.
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Photo attachment dicts, the shared stored shape (keys in the
    # marketplace namespace for standalone uploads AND for the
    # copies made from an inventory item at creation).
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # active | sold | removed (LISTING_STATUSES). Sold/removed
    # listings leave the public board; the row persists — a sold
    # listing is the reputation record's anchor.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )
    buyer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DealInteraction(Base):
    """One completed deal between two people — the rateable unit."""

    __tablename__ = "deal_interactions"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_interaction_dedupe"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The two parties, SORTED (the messaging pair pattern) — plain
    # columns + name snapshots so the record survives deletion of
    # either account (see module docstring).
    party_low_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    party_high_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    party_low_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    party_high_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    # listing | part | thread (INTERACTION_SOURCES): what the deal
    # was about. `thread` never occurs in practice today (only
    # anchored threads complete, and they take their anchor's
    # source) — the value exists so the vocabulary is closed.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="listing")
    listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    part_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # The listing/part title at completion — the label both sides
    # rate under, stable after edits and deletions.
    context_title: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    # "listing:<id>" | "thread:<id>" — one interaction per deal,
    # enforced by the DB, not by hope.
    dedupe_key: Mapped[str] = mapped_column(String(80), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Rating(Base):
    """One side's rating of the other for one interaction."""

    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint(
            "interaction_id", "rater_id", name="uq_rating_interaction_rater"
        ),
        CheckConstraint("stars >= 1 AND stars <= 5", name="ck_ratings_stars"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    interaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deal_interactions.id"),
        nullable=False,
        index=True,
    )
    # Plain columns (no FK): a deleted rater's stars stay counted,
    # displayed as "Former member" (see module docstring).
    rater_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    ratee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # NULL = still private (double-blind hold). Set when the pair
    # publishes together, or by the 14-day rule for a lone rating.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Moderator removal (gap wave 1, 2026-10-20): a moderator can
    # remove an abusive PUBLISHED rating through the moderation
    # queue. The row is NEVER deleted (append-only history): at
    # removal the text is replaced in place by the placeholder,
    # removed_at/removed_by_id stamp the act, and every aggregate
    # (reputation.summary_for and everything it feeds) excludes
    # the rating from that moment on. The interaction record and
    # the OTHER side's rating are untouched.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RatingReport(Base):
    """One member's report of one published rating, feeding the
    moderation queue's Ratings section (gap wave 1, 2026-10-20).
    The message_reports shape, one module over: a moderator
    dismisses the report (the rating stands) or removes the
    rating (the report becomes "actioned")."""

    __tablename__ = "rating_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rating_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ratings.id"),
        nullable=False,
        index=True,
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # open | dismissed | actioned (mirrors message_reports).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolution: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ThreadCompletion(Base):
    """One participant's "we completed a deal" close on an
    anchored thread. The second side's row creates the
    interaction (reputation.create_interaction_for_thread)."""

    __tablename__ = "thread_completions"
    __table_args__ = (
        UniqueConstraint("thread_id", "user_id", name="uq_thread_completion_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
