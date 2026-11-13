"""Inventory module tables.

Owned exclusively by the inventory module. Borrowing/claims/reports read
inventory data via service.py, never by importing these models.

Cost fields (per blueprint): purchase_price + purchase_date (what you paid),
replacement_cost (live/cached), msrp (today's list price). Photos/documents
are URL references to object storage — never blobs in the DB.
"""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FieldDefinition(Base):
    """User-defined custom field, e.g. VIN / engine size / part number.

    Owned by the inventory module AND by one user (owner_id): definitions
    are per-user, never platform-global — one user's required field must
    not block another user's tools, and deleting a definition may only
    scrub that owner's values. Values live in tools.custom_data keyed by
    definition id; definitions carry the type rules and search behavior.
    item_type is the APPLIES-TO axis: 'tool' definitions apply to
    tools only, 'battery' to batteries only, 'both' to either
    ('tool' is the default — pre-battery definitions are unchanged).
    'part' (Used Parts module, 2026-10-19) applies to used parts
    only — and parts take ONLY 'part' definitions ('both' keeps its
    tools+batteries meaning; see custom_fields._applies_to).
    """

    __tablename__ = "field_definitions"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "item_type", "name", name="uq_field_definitions_type_name"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String(50), nullable=False, default="tool")
    # URL-safe slug, unique per item_type: "vin", "engine_size".
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    # One of: text | number | date | dropdown | boolean
    field_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    searchable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Allowed values for dropdowns, e.g. ["New", "Used", "Refurbished"].
    options: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Warranty types (gap wave 1, 2026-10-20). NULL on a record means
# "not specified" — the months clock rules exactly as before the
# structured fields existed. "lifetime" is the only type that
# changes the computation (permanently in warranty, no end date);
# "term" and "limited" label the same months clock.
WARRANTY_TYPES = ("term", "lifetime", "limited")


# Item standing (Package B, 2026-10-19): the ONE authority for an
# item's availability state on tools and batteries. in_service /
# broken / in_repair are the repair trio the maintenance module
# drives through repair cycles; lost / stolen are owner-declared
# (bulk edit / the app's lost tools at migration). `repair_state`
# remains as a mirrored legacy column for the trio (see
# service.apply_standing); set pieces keep their own repair_state
# only — pieces are not assets and carry no standing.
STANDING_IN_SERVICE = "in_service"
STANDING_BROKEN = "broken"
STANDING_IN_REPAIR = "in_repair"
STANDING_LOST = "lost"
STANDING_STOLEN = "stolen"
# SOLD (wave 2, 2026-10-20): the item left the vault through a
# sale. Unlike lost/stolen — which stay IN the entitlement active
# set with badges (the owner still owns them and may recover
# them) — a sold item is GONE: billing's active set excludes it
# entirely (no slot consumed, never in the active ids), and the
# sale itself lives in sale_records. apply_standing writes it
# like any non-trio standing: repair_state keeps its trio value.
STANDING_SOLD = "sold"
# REPLACED (claims two-types, 2026-10-25): the item broke and the
# owner replaced it. The old record is RETIRED — out of the lists,
# search, sharing and the entitlement active set, mirroring SOLD's
# exclusions — but never deleted: reports, claims and history
# still read it, and the replacement is a NEW item carrying the
# old one's data. System-set only (the broken-item Replace flow):
# deliberately NOT in STANDINGS, so no user surface (bulk edit,
# standing filters) can set it or ask for it.
STANDING_REPLACED = "replaced"
STANDINGS = (
    STANDING_IN_SERVICE,
    STANDING_BROKEN,
    STANDING_IN_REPAIR,
    STANDING_LOST,
    STANDING_STOLEN,
    STANDING_SOLD,
)
REPAIR_TRIO = (STANDING_IN_SERVICE, STANDING_BROKEN, STANDING_IN_REPAIR)
# Standings that refuse a NEW lend (borrowing): anything that isn't
# in service. Returns never consult standing.
NON_LENDABLE_STANDINGS = (
    STANDING_BROKEN,
    STANDING_IN_REPAIR,
    STANDING_LOST,
    STANDING_STOLEN,
    STANDING_SOLD,
    STANDING_REPLACED,
)


class InventoryLocation(Base):
    """One node of the owner's INVENTORY location tree (Package B,
    2026-10-19) — Ryan's organizing model: the top tier is the
    toolbox / place ("Shop Toolbox"), drawers and shelves nest
    under it, and picking a place shows everything beneath it.

    parent_id points UP (child -> parent); NULL is a root. This is
    a SEPARATE tree from the Used Parts tree (part_locations) — a
    warehouse bin and a toolbox drawer are different worlds. The
    free-text `location` column on tools/batteries remains as the
    denormalized PATH string ("Shop Toolbox / Left Drawer 2") the
    service keeps in sync; `location_id` is the structure.
    Deleting a node with children or items is a service-level
    decision (reassign or detach, never a silent orphan) — the FK
    carries no cascade so the database backs the service up.
    """

    __tablename__ = "inventory_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_locations.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Drawer-grid positions (completeness audit A3, 2026-10-22 —
    # the app's fields verbatim): a node that is a DRAWER inside a
    # toolbox points at the layout (toolbox) node via
    # parent_layout_id and carries its position as drawer_index.
    # NULL/NULL on ordinary nodes — existing trees are untouched.
    parent_layout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_locations.id"),
        nullable=True,
        index=True,
    )
    drawer_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Battery(Base):
    """A battery pack as a FIRST-CLASS asset record (owner spec
    2026-10-18): batteries have their own serials, photos, receipts,
    warranties and defect windows, independent of any tool — so they
    are their own table, NOT children of tools. The optional
    `currently_in_tool_id` link lives HERE, on the battery: a
    battery migrates between tools and outlives them (the FK is
    ON DELETE SET NULL, and the inventory service also clears the
    link explicitly on tool delete, so a battery survives its tool
    everywhere, not just where FK actions run).

    Warranty status is COMPUTED from purchase_date + warranty_months
    (see service.warranty_status) — never stored, so it can never
    go stale. Money fields mirror Tool's exactly (blueprint: cost
    semantics are uniform across asset kinds)."""

    __tablename__ = "batteries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Normalized model number (scale fix, 2026-10-26; audit B9):
    # the comparison form of `model` (trim / collapse whitespace /
    # casefold — the importer's merge-dedupe rule), maintained by
    # the mapper listeners at the foot of this file on EVERY ORM
    # write, never set by hand. Indexed so SQL consumers can
    # narrow by model through an index instead of a per-row
    # lower() scan. Mirrors Tool.model_norm exactly.
    model_norm: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", index=True
    )
    serial_number: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    condition: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    # Batteries are assets in the Batteries category unless the
    # owner says otherwise — the peer payload and category filters
    # read it. (Was the singular "Battery" until the preinstalled
    # Batteries starter landed, owner spec 2026-10-25; the seed
    # rewrites the legacy spelling onto this one.)
    category: Mapped[str] = mapped_column(
        String(200), nullable=False, default="Batteries"
    )
    location: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # The location TREE node this item is filed under (Package B).
    # `location` above is the node's denormalized PATH string, kept
    # in sync by the service. SET NULL if the node goes (the service
    # reassigns/detaches first; this is the backstop).
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_locations.id", ondelete="SET NULL"),
        index=True,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    purchase_date: Mapped[date | None] = mapped_column()
    replacement_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    msrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Battery-specific facts.
    platform: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    voltage: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    capacity_ah: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    chemistry: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    # Structured warranty details (gap wave 1, 2026-10-20) — mirror
    # Tool's exactly: who stands behind the warranty, how to reach
    # them, the terms in short text, and the warranty TYPE. Type
    # NULL = unset (legacy rows): the months computation rules,
    # byte-identical to before. "lifetime" computes as permanently
    # in-warranty with no end date; "term"/"limited" keep the
    # months logic (the type is a label on the same clock).
    warranty_provider: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    warranty_contact: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    warranty_terms: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    warranty_type: Mapped[str | None] = mapped_column(String(20))

    # Current repair standing (maintenance module, 2026-10-19):
    # in_service | broken | in_repair, plus the CURRENT problem text.
    # The standing lives here — like the dealer tag, a fact other
    # surfaces read off the record (borrowing refuses to lend a
    # broken item) — while the repair HISTORY lives on the item's
    # warranty claims (repairs ∪ claims merge, 2026-11-04; it used
    # to live in maintenance repair_records) and is never wiped.
    repair_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_service"
    )
    repair_problem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The item's STANDING (Package B) — the authority; repair_state
    # above mirrors it for the repair trio (service.apply_standing).
    standing: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_service"
    )

    # How many identical units this record stands for (>= 1). Money
    # fields are PER UNIT — every total multiplies by quantity (item
    # structure package, 2026-10-18: the app's "Price Each" rule).
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Dealer tag (dealers module): "who made/sold this" — a plain
    # reference, never ownership. SET NULL if the company goes; the
    # tag HIDES everywhere when the dealers module is off for the
    # user, but the value is preserved (module removability).
    dealer_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="SET NULL"),
        index=True,
    )

    # The tool this battery currently sits in, if any. SET NULL on
    # tool delete: the battery record (and its warranty clock) is
    # untouched. Ownership is validated in the service layer — the
    # linked tool must belong to the same owner.
    currently_in_tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="SET NULL"),
        index=True,
    )

    # REPLACED marker (asset history build, 2026-10-20): the owner
    # retired this record in favor of a newer item. replaced_on is
    # the owner's date for the swap; replaced_by_item_id is a
    # PLAIN column (no FK — the ledger pattern: the marker must
    # survive the replacement record being deleted, and the id may
    # name a tool OR a battery). A replaced item STAYS in the
    # active set — the owner may still need it for claims — so the
    # entitlement engine never reads these fields. Mirrors Tool.
    replaced_on: Mapped[date | None] = mapped_column(Date)
    replaced_by_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )
    replaced_note: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )

    # Barcode / UPC (wave 4, 2026-10-20): the retail barcode the
    # item carries, typed, pasted or scanned at entry. Feeds the
    # layered lookup chain and duplicate detection (a shared UPC
    # is an identity signal). Mirrors Tool.upc exactly.
    upc: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Business use (audit A9): same flag as tools.
    business_use: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Health-check photo ignore (sweep E3, busy-work #5): the
    # owner has said this item's missing photo does not count
    # against it. Photo only — no other gap reads this flag.
    # Mirrors Tool.health_photo_ignored exactly.
    health_photo_ignored: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # User-defined custom fields: values keyed by field_definition
    # id — definitions with item_type 'battery' or 'both' apply.
    custom_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Object-storage references, same shape as Tool.attachments.
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Full-text search vector, maintained by a Postgres trigger
    # (see the batteries migration), same contract as tools.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Normalized model number (scale fix, 2026-10-26; audit B9):
    # see Battery.model_norm — the same contract, maintained by
    # the same listeners.
    model_norm: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", index=True
    )
    serial_number: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    condition: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # The location TREE node this item is filed under (Package B) —
    # `location` above is its denormalized PATH string. See Battery.
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_locations.id", ondelete="SET NULL"),
        index=True,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    purchase_date: Mapped[date | None] = mapped_column()
    replacement_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    msrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Warranty term in months (maintenance module, 2026-10-19) —
    # the same fact batteries carry. Warranty STATUS is computed
    # from purchase_date + warranty_months by ONE shared function
    # (service.warranty_status_for) so tools and batteries can
    # never drift into two behaviors.
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    # Structured warranty details (gap wave 1, 2026-10-20) — see
    # Battery's block: provider / contact / terms / type, with
    # "lifetime" computing as permanently in-warranty.
    warranty_provider: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    warranty_contact: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    warranty_terms: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    warranty_type: Mapped[str | None] = mapped_column(String(20))

    # Current repair standing (maintenance module) — see Battery.
    repair_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_service"
    )
    repair_problem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The item's STANDING (Package B) — the authority; repair_state
    # above mirrors it for the repair trio (service.apply_standing).
    standing: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_service"
    )

    # How many identical units this record stands for (>= 1). Money
    # fields are PER UNIT — purchase_price is the app's "Price Each"
    # and every total multiplies by quantity (item structure package,
    # 2026-10-18). A SET is NOT quantity: a set is distinct pieces on
    # one record (see SetPiece); quantity is identical units.
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Physical size text ("1/2 in drive", "14 in", ...), free text
    # like the app's size field.
    size: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # Multi-value model / serial numbers (the app allows several of
    # each per item). The single columns above stay as the PRIMARY —
    # always the first list entry, kept in sync by the service — so
    # search, sharing payloads and older consumers keep their shape.
    model_numbers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    serial_numbers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Barcode / UPC (wave 4, 2026-10-20): see Battery.upc — the
    # two kinds carry the identical field by design.
    upc: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # Consumables get used up (blades, discs, fluids) — a plain flag
    # the reports/claims modules will lean on later.
    consumable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Re-buy info (completeness audit A7, 2026-10-22): where the
    # replacement comes from when a consumable runs out — store,
    # website, the store's SKU/part number, free notes. Meaningful
    # only while `consumable` is set; plain text like `size`.
    rebuy_store: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    rebuy_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    rebuy_sku: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    rebuy_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Business use (audit A9): the owner's own flag that this
    # tool earns its keep — the trigger fact for the insurance
    # sub-limit guidance (never computed, never shared).
    business_use: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Health-check photo ignore (sweep E3, busy-work #5): the
    # owner has said this item's missing photo does not count
    # against it. Photo only — the model/serial, purchase-date
    # and piece-serial gaps never read this flag. A dedicated
    # column (migration 0103), NOT custom_data: custom_data keys
    # must map to user field definitions (custom_fields invariant)
    # and the blob is copied into claim snapshots and peer-sharing
    # views, where a system flag does not belong.
    health_photo_ignored: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # SETS (owner's model, 2026-10-18): a set IS a tool record — own
    # name, own set part number (its model field), own price, own
    # photos/receipts — whose pieces live in set_pieces. A tool is a
    # set by designation (this flag), not merely by having pieces.
    is_set: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Addon attachment: a standalone tool attached INTO a set as an
    # addon. Attached tools vanish from the top-level list and the
    # billing count, live inside the set's addon section, and detach
    # back to standalone (with their own prices) cleanly. SET NULL if
    # the set goes — the tool survives as a standalone.
    attached_to_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="SET NULL"),
        index=True,
    )

    # Dealer tag (dealers module) — same contract as Battery's.
    dealer_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="SET NULL"),
        index=True,
    )

    # REPLACED marker (asset history build, 2026-10-20) — see
    # Battery's block: date + plain-column replacement id (may
    # name a tool or a battery) + note. Replaced items stay in
    # the active set; entitlements never read these fields.
    replaced_on: Mapped[date | None] = mapped_column(Date)
    replaced_by_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )
    replaced_note: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )

    # User-defined custom fields: values keyed by field_definition id.
    custom_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # URLs into object storage (photos, receipts, documents). Never blobs.
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Full-text search vector, maintained by a Postgres trigger (see the
    # Alembic migration). Covers name/brand/model/serial/notes/location plus
    # searchable custom-field values. Never written by the app.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SetPiece(Base):
    """One piece of a set (item structure package, owner 2026-10-18).

    CORE pieces belong to the set from the factory; ADDON pieces
    were bought later to extend the set. Every piece, core included,
    may carry its OWN optional price (owner 2026-10-25, superseding
    the original "core pieces carry no price" rule + its CHECK,
    dropped by migration 0059): the price is the piece's own
    cost/replacement figure — replacing one lost socket costs money,
    and sets get built a piece at a time. A piece price NEVER rolls
    into the set's own price or totals; only ADDON prices join a
    set's totals (the bought-later money), exactly as before. Every
    piece carries identity fields (part + serial) so the claims
    module can claim a single piece or the whole set.

    Pieces are NOT assets: they never count toward plan limits, never
    appear in the top-level inventory list, and carry their own small
    attachment list (a photo of the broken socket, its receipt).
    """

    __tablename__ = "set_pieces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # core | addon
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="core")
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    part_number: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    serial_number: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # present | missing | sold | removed — gone pieces drop out of
    # totals/claims but stay in history.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="present")
    # Current repair standing (maintenance module, 2026-10-19) —
    # DISTINCT from the presence status above: a piece can be
    # present AND broken (the owner's one-socket-of-the-set case).
    repair_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_service"
    )
    repair_problem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # What the piece cost / would cost to replace (owner 2026-10-25:
    # any piece may carry one; the set's own price never reads it).
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ImportSession(Base):
    """One uploaded spreadsheet awaiting mapping + import (general
    importer, 2026-10-19).

    The RAW FILE BYTES live here, server-side, against the session —
    the client uploads once, then dry-run / confirm re-derive
    everything from these bytes, so a mapping change never needs a
    re-upload and a dry run can never disagree with the confirm that
    follows it. Sessions are owner-scoped (a foreign session id is a
    404, never a 403 — ids don't leak) and EXPIRE 24h after upload;
    confirming an import consumes (deletes) the session, and account
    deletion takes them too. Files are size-capped at upload
    (importer.MAX_FILE_BYTES), so the blob stays small.
    """

    __tablename__ = "import_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # 'tool' | 'battery' — set at upload (default 'tool') and
    # re-stamped by dry-run/confirm, which carry the kind the user
    # actually mapped against.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="tool")
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 'csv' | 'xlsx' — the parser is chosen by extension AND verified
    # by parsing; this records which one succeeded.
    file_format: Mapped[str] = mapped_column(String(10), nullable=False, default="csv")
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Detected header row (verbatim, duplicates kept — columns are
    # addressed by INDEX everywhere, never by name).
    headers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ImportValueMapping(Base):
    """One LEARNED import answer (smart value matching, 2026-10-19).

    When an import's Resolve step asks about a value ("is your
    dealer 'matco' the same as 'Matco Incorporated'?"), the user's
    answer lands here, keyed by (owner, field, normalized raw) —
    the next import carrying the same value is pre-answered from
    this row, still LISTED in the resolve plan and the import
    summary (nothing invisible), and the user can delete the row
    in Settings → Import matching to make the system ask again.

    `action` is what to do with the raw value: map (to target_id /
    target_value), create (as a brand-new value), or unset (drop
    it). Targets: dealer + location resolutions point at a row
    (target_id = company / tree node); brand / category / tag
    resolutions carry the canonical string (target_value). If a
    pointed-at target later disappears, the learned row goes stale
    and the resolve step asks again rather than guessing.
    """

    __tablename__ = "import_value_mappings"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "field", "normalized",
            name="uq_import_value_mappings_owner_field_normalized",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # The importer field key: dealer_name | brand | category |
    # tags | location.
    field: Mapped[str] = mapped_column(String(20), nullable=False)
    # The value as it appeared in the file (first-seen spelling).
    raw_value: Mapped[str] = mapped_column(String(500), nullable=False)
    # The matching key the raw was normalized to (matching.py).
    normalized: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    # map | create | unset
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    target_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Tag(Base):
    """A per-user tag (item structure package, 2026-10-18): the
    owner's own vocabulary for slicing inventory ("truck box",
    "warranty 2027", ...). Names are unique per owner; creating a
    duplicate name (any capitalization) returns the existing tag —
    the app's rule. Links live in item_tags."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_tags_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(30), nullable=False, default="amber")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ItemTag(Base):
    """One item <-> tag link. Items are tools or batteries (item_kind);
    the unused FK stays NULL. Links die with their item or their tag
    (CASCADE) — a deleted tag simply falls off every item."""

    __tablename__ = "item_tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    item_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="tool")
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), index=True
    )
    battery_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batteries.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InventoryCategory(Base):
    """One owner-registered category name (category manager, gap
    wave 1, 2026-10-20).

    Categories still LIVE as free text on tools/batteries — that
    string is the denormalized fact every surface reads, exactly
    like the location path. This table is the manager's registry:
    it lets a category EXIST with zero items (created ahead of
    filing), and it anchors rename/merge/delete so the manager
    can list a category even after its last item moves away.

    Uniqueness is on the NORMALIZED key (importer matching's
    normalize_match_value: casefold + punctuation folding), so
    "Power Tools" and "power tools" are one category — the
    duplicate-folding rule the manager enforces. `name` keeps the
    owner's preferred display spelling.
    """

    __tablename__ = "inventory_categories"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "normalized", name="uq_inventory_categories_owner_normalized"
        ),
        # One row per starter per owner (migration 0056); NULL
        # system_keys (user categories) stay unconstrained.
        Index(
            "uq_inventory_categories_owner_system_key",
            "owner_id",
            "system_key",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # The display spelling the owner picked.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # normalize_match_value(name) — the identity of the category.
    normalized: Mapped[str] = mapped_column(String(500), nullable=False)
    # Starred (owner spec 2026-10-24): the owner's shortcut set —
    # starred categories surface as links in the Inventory view
    # row. Capped at 5 per owner, enforced in the service. The
    # flag lives on the registry row, so a rename carries the
    # star with it and a delete / merge-source takes the star
    # with the row.
    starred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Preinstalled starter categories (owner spec 2026-10-25):
    # every account is seeded with Batteries / Hand Tools /
    # Power Tools / Pneumatic Tools, starred. `system_key` names
    # WHICH starter a row is ("batteries" | "hand_tools" |
    # "power_tools" | "pneumatic_tools"); NULL = a user's own
    # category. The key — never the display name — is the
    # identity: the three tool starters may be renamed (the key
    # rides along), while "batteries" is fixed-name because
    # battery records are wired to it. Preinstalled rows cannot
    # be deleted (service-enforced).
    system_key: Mapped[str | None] = mapped_column(
        String(40), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ItemLossReport(Base):
    """One lost/stolen report on one item (gap wave 1, 2026-10-20).

    The item's STANDING (lost/stolen) says WHAT state it's in;
    this record carries the paper trail a report needs: when it
    was reported, the police report number/department, the
    insurer and claim number on file, and free notes. An item has
    at most ONE ACTIVE report (partial unique index below);
    marking the item recovered closes the report with a
    recovered_date — the row is KEPT as history, never deleted,
    so the panel can show past reports and a later loss starts a
    fresh report.

    item_id is deliberately NOT a foreign key (the checkout-ledger
    shape): the inventory service deletes an item's reports with
    the item (ORM deletes, so the change journal captures them),
    and the account-deletion cascade sweeps by owner_id.
    """

    __tablename__ = "item_loss_reports"
    __table_args__ = (
        # One active report per item, enforced by the database
        # (the service pre-checks for a friendly error; this is
        # the race-proof backstop — Postgres partial index + its
        # SQLite twin, the checkouts pattern).
        Index(
            "uq_loss_reports_one_active_per_item",
            "item_kind",
            "item_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # tool | battery
    item_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # active | recovered
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # Which standing the report was opened under: lost | stolen.
    standing: Mapped[str] = mapped_column(String(20), nullable=False, default="lost")
    reported_date: Mapped[date | None] = mapped_column(Date)
    police_report_number: Mapped[str] = mapped_column(
        String(100), nullable=False, default=""
    )
    police_department: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    insurer_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    claim_number: Mapped[str] = mapped_column(
        String(100), nullable=False, default=""
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recovered_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SaleRecord(Base):
    """One sale (or its reversal) in the SOLD ledger (wave 2,
    2026-10-20).

    The ledger is append-only in spirit: a sale row is never
    edited or deleted through any surface. Correcting a sale is
    the Undo action, which writes a COMPENSATING row (kind
    "reversal", reverses_id naming the sale it cancels) and
    restores the item — history stays honest about both events.

    item_kind is tool | battery | set_piece. item_id / set_id /
    reverses_id are deliberately NOT foreign keys (the checkout-
    ledger shape): the record outlives the item — it carries the
    item_name snapshot — and the account-deletion cascade sweeps
    by owner_id. For a piece sale, item_id is the PIECE and
    set_id its parent set; for a whole-set sale the record rides
    the set's own tool id with item_kind "tool".

    sale_price is the TOTAL for the units in quantity_sold (not
    per-unit): a partial sale of 2 of 5 records what those 2
    fetched. source is manual | migrated (the app converter maps
    its sold items here later; nothing writes "migrated" yet).
    """

    __tablename__ = "sale_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    item_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    set_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    item_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    quantity_sold: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    buyer_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    buyer_contact: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    sale_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    sold_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # manual | migrated
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    # sale | reversal
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="sale")
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Monotonic insertion order (the borrowing seq precedent,
    # 2026-10-19): created_at ties at second resolution on SQLite,
    # and the Undo LIFO discipline needs a true "which sale came
    # later". Assigned by the before_insert hook below; migration
    # 0040 creates the `sale_records_seq` sequence on Postgres.
    seq: Mapped[int | None] = mapped_column(BigInteger)


class AcquisitionRecord(Base):
    """One acquisition event in the ACQUISITION ledger
    (year-end fix, 2026-10-24).

    WHY THIS EXISTS: the year-end report's Acquired section used
    to be computed from each item's CURRENT quantity
    (purchase_price × quantity), so a partial sale rewrote
    purchase history — bought 3 × $149, sold 1, and the report
    claimed only 2 / $298 were ever acquired. This ledger is the
    permanent record of what was actually acquired: one row per
    acquisition event (item creation, plus each quantity INCREASE
    via edit), written by the inventory service at the moment it
    happens. Sales, sale reversals, quantity decreases and item
    deletion NEVER remove or shrink a row — the purchase still
    happened that year.

    The sold ledger's shape, mirrored: item_id is deliberately
    NOT a foreign key (the record outlives the item) and the
    item's name / brand / business-use flag are SNAPSHOTS, so a
    deleted item's acquisitions still report correctly and the
    tax worksheet's business split uses the flag as it stood at
    acquisition time. unit_price / acquired_on snapshot the
    item's purchase facts at write time; later edits to the
    item's price or date do not rewrite this history (the
    journal/restore seam restores ITEMS, never ledger rows).
    Account deletion sweeps these rows by owner_id, exactly like
    the sold ledger.

    Rows are written only when the item carries a purchase price
    (a price-less acquisition records no money — the reports skip
    it, as they always have). Migration 0049 backfills one row
    per pre-existing priced tool/battery.
    """

    __tablename__ = "acquisition_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # tool | battery
    item_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    item_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    brand: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    business_use: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # The item's purchase_date at write time; NULL when the item
    # carried none (dateless acquisitions appear in no year's
    # report — the same rule the reports always applied).
    acquired_on: Mapped[date | None] = mapped_column(Date)
    quantity_acquired: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


@event.listens_for(SaleRecord, "before_insert")
def _assign_sale_seq(mapper, connection, target):  # noqa: ANN001, ANN202
    """Give every new sale record the next sequence value
    (borrowing's _assign_checkout_seq, mirrored): Postgres draws
    from the real sequence; SQLite takes max+1 in-transaction."""
    if target.seq is not None:
        return
    if connection.dialect.name == "postgresql":
        target.seq = connection.scalar(text("SELECT nextval('sale_records_seq')"))
    else:
        target.seq = connection.scalar(
            text("SELECT COALESCE(MAX(seq), 0) + 1 FROM sale_records")
        )


# -- model_norm maintenance (scale fix, 2026-10-26) ---------------------------
#
# tools.model_norm / batteries.model_norm carry the comparison
# form of the primary model (see the column comments). They are
# maintained HERE, at the mapper, so every write path — item
# forms, the wizard, the importer, claims' replace flow, test
# fixtures — carries the value without remembering to set it.
# The fold is the importer's merge-dedupe rule; its canonical
# copy lives in tool_expansion.service.norm_model (this module
# cannot import that one — tool_expansion imports these models),
# and a parity test pins the two together.

_MODEL_WHITESPACE = re.compile(r"\s+")


def _model_norm(value) -> str:  # noqa: ANN001, ANN202
    if not value:
        return ""
    return _MODEL_WHITESPACE.sub(" ", str(value).strip()).casefold()


@event.listens_for(Tool, "before_insert")
@event.listens_for(Tool, "before_update")
def _tool_model_norm(mapper, connection, target):  # noqa: ANN001, ANN202
    target.model_norm = _model_norm(target.model)


@event.listens_for(Battery, "before_insert")
@event.listens_for(Battery, "before_update")
def _battery_model_norm(mapper, connection, target):  # noqa: ANN001, ANN202
    target.model_norm = _model_norm(target.model)
