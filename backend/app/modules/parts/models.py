"""Used Parts module tables.

Owned exclusively by the parts module. Other modules read parts data
through service.py, never by importing these models.

The owner's model (2026-10-04, blueprint §18): a searchable used-parts
section for spares kept for future use, scaling from home spares to
warehouse shops. Two tables carry the whole module:

- part_locations — the owner's OWN location tree (warehouse → aisle →
  bin, or whatever shape their shelves take). Levels are labels; the
  tree is the structure. This tree belongs to the parts module alone —
  tools keep their free-text location and never touch it.
- parts — one spare. Deliberately MINIMAL core (title, quantity,
  condition, notes, photos): everything specific (year, make, model,
  VIN, engine, part number, OEM number, side, position) is a
  USER-DEFINED field through the shared custom-fields engine
  (field_definitions with item_type 'part'; values in custom_data,
  the same pattern tools use). A warehouse's schema is theirs to
  invent — the module never hard-codes vehicle/part columns.

Parts are NOT assets: they never count toward the entitlement item
cap (a spare on a shelf is not a tool in the vault — the owner's cap
counts tools + batteries through billing's active set, which never
reads these tables), and converting a part to a tool is a one-way
COPY through inventory's service interface, never a move.
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# The location levels the tree manager offers. Labels, not structure:
# any node may parent any other (a bin straight under a warehouse is
# a small shop's honest shape); cycles are the only forbidden shape.
LOCATION_LEVELS = ("warehouse", "aisle", "bin", "shelf", "other")


class PartLocation(Base):
    """One node of the owner's parts-location tree.

    parent_id points UP (child -> parent); NULL is a root (usually a
    warehouse, but the module doesn't enforce it). Deleting a node
    with children or parts is a service-level decision (reassign or
    detach, never a silent orphan) — the FK carries no cascade so
    the database backs the service up.
    """

    __tablename__ = "part_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("part_locations.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # warehouse | aisle | bin | shelf | other (LOCATION_LEVELS).
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="other")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PartPoolSettings(Base):
    """One owner's Community Parts pool choices (2026-10-19).

    - default_visibility: what a part does when neither its own
      override nor a category setting speaks — "private" unless
      the owner flips the whole shelf public ("choose all").
    - category_visibility: {category label: "public" | "private"}
      — the per-category opt-in/out the owner asked for.

    One row per owner, created lazily on first read. Resolution
    order (pool.resolve_visibility): the part's own visibility
    override wins, then its category's setting, then this default.
    """

    __tablename__ = "part_pool_settings"

    # Surrogate id like every journaled entity (the audit trail
    # keys its entries on it); owner_id is the unique lookup.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    default_visibility: Mapped[str] = mapped_column(
        String(10), nullable=False, default="private", server_default="private"
    )
    category_visibility: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Part(Base):
    """One used part / spare the owner is keeping.

    Photos ride the shared attachment machinery (photo kind only) as
    storage KEYS in `attachments` — the same stored shape tools use,
    namespaced {owner}/parts/{id}/photo/...

    converted_tool_id records the "Add to Asset Inventory" copy: the
    tool the part was copied into (latest copy wins). It is a link,
    not a move — the part row is untouched by conversion and the FK
    SET NULLs if the tool is later deleted.
    """

    __tablename__ = "parts"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="ck_parts_quantity_min"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    condition: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("part_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # User-defined values keyed by field_definition id — definitions
    # with item_type 'part' apply (custom-fields engine, inventory).
    custom_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # -- Community Parts pool (2026-10-19) ------------------------------
    # The STANDARD vehicle fields the community index searches on.
    # They are core columns (not custom fields) on purpose: owners
    # name their custom fields differently ("Year" vs "vehicle
    # year"), so cross-user search needs one shared vocabulary.
    # Everything else specific stays in custom_data.
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    make: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    engine: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # The owner's own category label ("Engine", "Suspension", …) —
    # the unit the pool's per-category visibility setting keys on.
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", index=True
    )
    # Optional asking price for the pool listing (money semantics
    # match the rest of the platform: a bare amount, no currency
    # machinery — users settle off-platform, owner 2026-10-19).
    asking_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # Per-part listing overrides (NULL = inherit):
    # - public_area_label overrides the profile's coarse area.
    # - visibility: "public" | "private" beats the category
    #   setting, which beats the owner's pool default.
    # - show_phone_override beats the profile's show_phone toggle.
    public_area_label: Mapped[str | None] = mapped_column(String(120))
    visibility: Mapped[str | None] = mapped_column(String(10))
    show_phone_override: Mapped[bool | None] = mapped_column(Boolean)

    # Object-storage references, same shape as Tool.attachments.
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    converted_tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
