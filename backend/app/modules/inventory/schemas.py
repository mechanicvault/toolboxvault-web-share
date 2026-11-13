"""Inventory module schemas."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Column-mirroring bounds (deep audit F4-02/F4-03). The money columns
# are Numeric(12, 2) and the battery spec columns Numeric(6, 2);
# Parts/Claims already reject negatives with ge=0, and core's signup
# schema was hardened for this exact class in 2026-10 — inventory was
# the inconsistent one: negative prices stored verbatim, and a
# 5,000-char name or 30-digit price reached Postgres and came back as
# a 500. Every bound below mirrors its column so bad input is a
# clean 422 at the schema door, never a stored negative or a crash.
MoneyValue = Annotated[Decimal, Field(ge=0, le=Decimal("9999999999.99"))]
SmallDecimalValue = Annotated[Decimal, Field(ge=0, le=Decimal("9999.99"))]
# Free-text columns are Text (no DB length), but unbounded input is
# still abuse-shaped; the cap is far above any real note (and above
# the largest note the F4 probes found the API accepting, ~600 KB).
NOTES_MAX_LENGTH = 1_000_000
NumberList = list[Annotated[str, Field(max_length=200)]]


# -- tags ------------------------------------------------------------------
class TagPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str = "amber"
    # How many of the owner's items carry the tag (0 on item payloads
    # where the count isn't computed).
    item_count: int = 0


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="amber", max_length=30)


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=30)


# -- tools ---------------------------------------------------------------
class InitialSchedule(BaseModel):
    """An optional first maintenance schedule riding an item save
    (Package B). The routes hand it to the maintenance service
    after the item exists; validation of the schedule itself
    (a kind, and an interval OR a due date) lives there."""

    kind: str = Field(pattern="^(calibration|service|inspection|other)$")
    label: str = Field(default="", max_length=300)
    interval_days: int | None = Field(default=None, ge=1, le=36500)
    due_date: date | None = None
    last_done_at: date | None = None


class TruckChargeIn(BaseModel):
    """The Add wizard's truck-account charge (2026-10-31): put a
    PORTION of this item's purchase price on the buyer's truck
    account with the item's dealer company. `amount` is the
    portion (the service validates 0 < amount <= purchase_price);
    `account_id` picks among several active accounts with that
    dealer — omitted, the truck service charges the only active
    account or opens a self-tab when there is none. Create-only:
    editing an item never re-asks."""

    amount: Decimal = Field(gt=0)
    account_id: uuid.UUID | None = None
    # The wizard's agent pick (multi-preferred, 2026-11-05):
    # charge THIS agent's truck tab instead of the display
    # default's. Validated against the buyer's roster for the
    # dealer by the truck service.
    agent_user_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID | None = None


class ToolCreate(BaseModel):
    name: str = Field(max_length=300)
    brand: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    serial_number: str = Field(default="", max_length=200)
    # Condition is DORMANT (Package B, Ryan-directed): no user
    # surface shows it anymore; the field stays accepted so the
    # importer keeps preserving source data in the column, and
    # exports keep carrying it. Nothing reads it back out.
    condition: str = Field(default="", max_length=50)
    category: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    # The location TREE node (Package B): when sent, it wins and
    # `location` becomes the node's path. Text-only writes resolve
    # to a top-level node (see service._apply_location_write).
    location_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=NOTES_MAX_LENGTH)
    # Money is PER UNIT ("Price Each" in the app): purchase_price is
    # what ONE unit cost; the record's total is price x quantity.
    purchase_price: MoneyValue | None = None
    purchase_date: date | None = None
    replacement_cost: MoneyValue | None = None
    msrp: MoneyValue | None = None
    # Warranty term in months (maintenance build, 2026-10-19) —
    # mirrors BatteryCreate; status is computed at read time.
    warranty_months: int | None = Field(default=None, ge=0, le=1200)
    # Structured warranty details (gap wave 1, 2026-10-20).
    warranty_provider: str = Field(default="", max_length=200)
    warranty_contact: str = Field(default="", max_length=300)
    warranty_terms: str = Field(default="", max_length=500)
    warranty_type: str | None = Field(
        default=None, pattern="^(term|lifetime|limited)$"
    )
    quantity: int = Field(default=1, ge=1, le=100000)
    size: str = Field(default="", max_length=200)
    # Multi-value model/serial numbers; the service syncs the single
    # columns as the primary (first entry). Sending only the single
    # field seeds the list with it.
    model_numbers: NumberList | None = Field(default=None, max_length=50)
    serial_numbers: NumberList | None = Field(default=None, max_length=50)
    # Barcode / UPC (wave 4): typed, pasted or scanned at entry.
    upc: str = Field(default="", max_length=64)
    consumable: bool = False
    business_use: bool = False
    # Re-buy info (audit A7): where the replacement comes from.
    rebuy_store: str = Field(default="", max_length=200)
    rebuy_url: str = Field(default="", max_length=500)
    rebuy_sku: str = Field(default="", max_length=120)
    rebuy_notes: str = Field(default="", max_length=4000)
    is_set: bool = False
    # Dealer tag (dealers module): a directory company or one of the
    # owner's own private companies; validated in the service.
    dealer_company_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    # Values keyed by field-definition id (or name slug); validated in service.
    custom_data: dict = {}
    # Inline set editor (Package B): the set's pieces ride the same
    # save when is_set — validated and applied atomically by the
    # service. None = not a set save (no piece changes).
    pieces: list["SetPieceInline"] | None = Field(default=None, max_length=500)
    # Build-a-set from inventory (owner 2026-10-25): the ids of the
    # owner's standalone tools folded INTO this set as attached
    # pieces. Like `pieces`, the list is the DESIRED set of attached
    # tools — the service attaches new ids and detaches ones no
    # longer listed. None = leave attachments alone.
    attach_tool_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    # Optional first maintenance schedule, created by the route via
    # the maintenance service once the item exists.
    initial_schedule: InitialSchedule | None = None
    # The wizard's truck-account charge (2026-10-31) — applied by
    # the service inside the create transaction; see TruckChargeIn.
    truck_charge: TruckChargeIn | None = None


class ToolUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    serial_number: str | None = Field(default=None, max_length=200)
    condition: str | None = Field(default=None, max_length=50)  # dormant
    category: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    location_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)
    purchase_price: MoneyValue | None = None
    purchase_date: date | None = None
    replacement_cost: MoneyValue | None = None
    msrp: MoneyValue | None = None
    warranty_months: int | None = Field(default=None, ge=0, le=1200)
    warranty_provider: str | None = Field(default=None, max_length=200)
    warranty_contact: str | None = Field(default=None, max_length=300)
    warranty_terms: str | None = Field(default=None, max_length=500)
    warranty_type: str | None = Field(
        default=None, pattern="^(term|lifetime|limited)$"
    )
    quantity: int | None = Field(default=None, ge=1, le=100000)
    size: str | None = Field(default=None, max_length=200)
    model_numbers: NumberList | None = Field(default=None, max_length=50)
    serial_numbers: NumberList | None = Field(default=None, max_length=50)
    upc: str | None = Field(default=None, max_length=64)
    consumable: bool | None = None
    business_use: bool | None = None
    rebuy_store: str | None = Field(default=None, max_length=200)
    rebuy_url: str | None = Field(default=None, max_length=500)
    rebuy_sku: str | None = Field(default=None, max_length=120)
    rebuy_notes: str | None = Field(default=None, max_length=4000)
    is_set: bool | None = None
    dealer_company_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    custom_data: dict | None = None
    # Inline set editor (Package B): the set's pieces ride the same
    # save. None = leave the pieces alone; a list REPLACES the set's
    # pieces with exactly those rows (see service._sync_set_pieces).
    pieces: list["SetPieceInline"] | None = Field(default=None, max_length=500)
    # Build-a-set from inventory (owner 2026-10-25): the DESIRED set
    # of tools attached into this set (see ToolCreate's note). None
    # = leave attachments alone; a list replaces them exactly.
    attach_tool_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    # Optional maintenance schedule created alongside this save.
    initial_schedule: InitialSchedule | None = None


class AttachmentPublic(BaseModel):
    key: str
    filename: str
    kind: str
    content_type: str
    size_bytes: int
    uploaded_at: str | None = None
    # Provenance (wave 4): set on files the system fetched itself
    # (origin "manual" — a located user manual): where the file
    # came from and when it was fetched. Null on user uploads.
    origin: str | None = None
    source_url: str | None = None
    source_name: str | None = None
    fetched_at: str | None = None
    url: str  # fresh presigned read URL, minted at read time
    # Size-appropriate renditions for list/tile slots (F3-12):
    # signed resize-on-read URLs, minted fresh like `url`; null
    # for non-photo attachments.
    thumb_url: str | None = None
    thumb_url_sm: str | None = None
    # Set when the file is tied to one of the item's lost/stolen
    # reports (its police-report document); null otherwise.
    loss_report_id: str | None = None


# -- set pieces --------------------------------------------------------------
class SetPiecePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    set_id: uuid.UUID
    kind: str  # core | addon
    name: str
    part_number: str
    serial_number: str
    status: str  # present | missing | sold | removed
    # Repair standing (maintenance build): in_service | broken |
    # in_repair — distinct from the presence status above.
    repair_state: str = "in_service"
    repair_problem: str = ""
    price: Decimal | None  # the piece's own price, any kind (2026-10-25)
    purchase_date: date | None
    sort_order: int
    attachments: list[AttachmentPublic] = []
    created_at: datetime
    updated_at: datetime


class SetPieceCreate(BaseModel):
    kind: str = Field(default="core", pattern="^(core|addon)$")
    name: str = Field(min_length=1, max_length=300)
    part_number: str = Field(default="", max_length=200)
    serial_number: str = Field(default="", max_length=200)
    status: str = Field(
        default="present", pattern="^(present|missing|sold|removed)$"
    )
    # Optional for EVERY piece, core included (owner 2026-10-25):
    # the piece's own cost / replacement figure. Never rolled into
    # the set's own price.
    price: MoneyValue | None = None
    purchase_date: date | None = None
    sort_order: int = 0


class SetPieceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    part_number: str | None = Field(default=None, max_length=200)
    serial_number: str | None = Field(default=None, max_length=200)
    status: str | None = Field(
        default=None, pattern="^(present|missing|sold|removed)$"
    )
    price: MoneyValue | None = None
    purchase_date: date | None = None
    sort_order: int | None = None
    # The piece's repair standing (repairs ∪ claims merge,
    # 2026-11-04): a piece follows the same rule as a whole item —
    # it can be marked broken (and back in service) as its own
    # step, with no claim. "in_repair" is NOT settable here: the
    # claim lifecycle drives it (service.update_set_piece refuses
    # to move a piece INTO in_repair; the pattern still admits the
    # value so a same-state echo validates).
    repair_state: str | None = Field(
        default=None, pattern="^(in_service|broken|in_repair)$"
    )
    repair_problem: str | None = Field(default=None, max_length=500)


class SetPieceInline(SetPieceCreate):
    """A piece row in the item form's inline set editor (Package B):
    SetPieceCreate's fields plus the existing piece's id on edits
    (absent = a new piece; a piece missing from the submitted list
    is removed — one form, one save)."""

    id: uuid.UUID | None = None


class SetSummary(BaseModel):
    """Counts for list cards: "Set · N core + M addons" (addons =
    addon pieces + attached tools)."""

    core_count: int = 0
    addon_count: int = 0


class AttachedToolRef(BaseModel):
    """An addon tool inside a set's payload: identity + its own
    money (it keeps its prices — they're part of the set's totals)."""

    id: uuid.UUID
    name: str
    brand: str = ""
    model: str = ""
    serial_number: str = ""
    quantity: int = 1
    purchase_price: Decimal | None = None
    purchase_total: Decimal | None = None
    replacement_cost: Decimal | None = None


class SetBlock(BaseModel):
    """The full set structure on a set's payload: pieces by kind,
    attached addon tools, and the set's money totals (set price x
    qty + addon prices; replacement likewise). Claims consume this
    shape later via resolve_set_members."""

    core_pieces: list[SetPiecePublic] = []
    addon_pieces: list[SetPiecePublic] = []
    attached_tools: list[AttachedToolRef] = []
    price_total: Decimal | None = None
    replacement_total: Decimal | None = None


class SetParentRef(BaseModel):
    id: uuid.UUID
    name: str


class ToolPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    brand: str
    model: str
    serial_number: str
    category: str
    location: str
    # Location tree (Package B): the filing node's id; `location`
    # above is its denormalized path string.
    location_id: uuid.UUID | None = None
    # The item's standing (Package B): in_service | broken |
    # in_repair | lost | stolen — the authority (repair_state's
    # trio is mirrored from it, never the reverse at read time).
    standing: str = "in_service"
    notes: str
    purchase_price: Decimal | None
    purchase_date: date | None
    replacement_cost: Decimal | None
    msrp: Decimal | None
    # Warranty (maintenance build, 2026-10-19): mirrors the battery
    # payload — term stored, standing + end date computed at read
    # time by the shared function. Never stored.
    warranty_months: int | None = None
    # Structured warranty details (gap wave 1): provider/contact/
    # terms as recorded; type term|lifetime|limited or null.
    warranty_provider: str = ""
    warranty_contact: str = ""
    warranty_terms: str = ""
    warranty_type: str | None = None
    warranty_status: str = "unknown"
    warranty_end_date: date | None = None
    # Replaced marker (asset history, 2026-10-20): the swap date,
    # the replacement item's id (either kind; may dangle), its
    # name resolved live, and the owner's note. Pure history —
    # a replaced item stays in the active set.
    replaced_on: date | None = None
    replaced_by_item_id: uuid.UUID | None = None
    replaced_by_name: str | None = None
    replaced_note: str = ""
    # Item structure package (2026-10-18): quantity (money is per
    # unit), size, multi-value numbers (primary columns above stay
    # in sync), consumable, dealer tag, tags, set structure.
    quantity: int = 1
    size: str = ""
    model_numbers: list[str] = []
    serial_numbers: list[str] = []
    upc: str = ""
    consumable: bool = False
    business_use: bool = False
    # A9 guidance: True when this item is business-use AND the
    # owner's own policy declares a business sub-limit on a
    # non-dedicated policy. Display-only; computed server-side.
    sub_limit_warning: bool = False
    rebuy_store: str = ""
    rebuy_url: str = ""
    rebuy_sku: str = ""
    rebuy_notes: str = ""
    is_set: bool = False
    attached_to_set_id: uuid.UUID | None = None
    attached_to_set: SetParentRef | None = None
    dealer_company_id: uuid.UUID | None = None
    # Null when the dealers module is off for the caller (the tag
    # hides; the stored id above is preserved server-side only in
    # that case — see serialize_tool's dealer_visible contract).
    dealer_company_name: str | None = None
    tags: list[TagPublic] = []
    set_summary: SetSummary | None = None
    set: SetBlock | None = None
    # Owner search marks a set found through its contents:
    # "piece" (a piece's part number/name) or "attached" (an
    # attached tool's identity); matched_label names the hit.
    matched_via: str | None = None
    matched_label: str | None = None
    custom_data: dict
    attachments: list[AttachmentPublic]
    created_at: datetime
    updated_at: datetime
    # Entitlement standing (billing): False = the tool is over the
    # owner's active plan limit while enforcement is on — visible in
    # the owner's list, greyed, and excluded from stats/sharing.
    # Defaults True so every non-entitlement read stays honest.
    active: bool = True


# -- batteries -------------------------------------------------------------
class BatteryCreate(BaseModel):
    name: str = Field(max_length=300)
    brand: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    serial_number: str = Field(default="", max_length=200)
    condition: str = Field(default="", max_length=50)  # dormant
    category: str = Field(default="Batteries", max_length=200)
    business_use: bool = False
    location: str = Field(default="", max_length=200)
    location_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=NOTES_MAX_LENGTH)
    purchase_price: MoneyValue | None = None
    purchase_date: date | None = None
    replacement_cost: MoneyValue | None = None
    msrp: MoneyValue | None = None
    platform: str = Field(default="", max_length=100)
    voltage: SmallDecimalValue | None = None
    capacity_ah: SmallDecimalValue | None = None
    chemistry: str = Field(default="", max_length=100)
    warranty_months: int | None = Field(default=None, ge=0, le=1200)
    # Structured warranty details (gap wave 1, 2026-10-20).
    warranty_provider: str = Field(default="", max_length=200)
    warranty_contact: str = Field(default="", max_length=300)
    warranty_terms: str = Field(default="", max_length=500)
    warranty_type: str | None = Field(
        default=None, pattern="^(term|lifetime|limited)$"
    )
    quantity: int = Field(default=1, ge=1, le=100000)
    # Barcode / UPC (wave 4) — mirrors ToolCreate.
    upc: str = Field(default="", max_length=64)
    # Dealer tag (dealers module) — same contract as tools.
    dealer_company_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    # The tool this battery currently sits in (owner's own tools
    # only — the service refuses foreign ids with a 422).
    currently_in_tool_id: uuid.UUID | None = None
    # Values keyed by field-definition id (or name slug); validated in service.
    custom_data: dict = {}
    # Optional first maintenance schedule (Package B) — created by
    # the route via the maintenance service once the item exists.
    initial_schedule: InitialSchedule | None = None
    # The wizard's truck-account charge (2026-10-31) — same
    # contract as ToolCreate.truck_charge.
    truck_charge: TruckChargeIn | None = None


class BatteryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    serial_number: str | None = Field(default=None, max_length=200)
    condition: str | None = Field(default=None, max_length=50)  # dormant
    category: str | None = Field(default=None, max_length=200)
    business_use: bool | None = None
    location: str | None = Field(default=None, max_length=200)
    location_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)
    purchase_price: MoneyValue | None = None
    purchase_date: date | None = None
    replacement_cost: MoneyValue | None = None
    msrp: MoneyValue | None = None
    platform: str | None = Field(default=None, max_length=100)
    voltage: SmallDecimalValue | None = None
    capacity_ah: SmallDecimalValue | None = None
    chemistry: str | None = Field(default=None, max_length=100)
    warranty_months: int | None = Field(default=None, ge=0, le=1200)
    warranty_provider: str | None = Field(default=None, max_length=200)
    warranty_contact: str | None = Field(default=None, max_length=300)
    warranty_terms: str | None = Field(default=None, max_length=500)
    warranty_type: str | None = Field(
        default=None, pattern="^(term|lifetime|limited)$"
    )
    quantity: int | None = Field(default=None, ge=1, le=100000)
    upc: str | None = Field(default=None, max_length=64)
    dealer_company_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    currently_in_tool_id: uuid.UUID | None = None
    custom_data: dict | None = None
    # Optional maintenance schedule created alongside this save.
    initial_schedule: InitialSchedule | None = None


class BatteryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    brand: str
    model: str
    serial_number: str
    category: str
    location: str
    location_id: uuid.UUID | None = None
    standing: str = "in_service"
    business_use: bool = False
    sub_limit_warning: bool = False
    notes: str
    purchase_price: Decimal | None
    purchase_date: date | None
    replacement_cost: Decimal | None
    msrp: Decimal | None
    platform: str
    voltage: Decimal | None
    capacity_ah: Decimal | None
    chemistry: str
    warranty_months: int | None
    warranty_provider: str = ""
    warranty_contact: str = ""
    warranty_terms: str = ""
    warranty_type: str | None = None
    # Computed from purchase_date + warranty_months at read time:
    # in_warranty | expiring_soon (<= 30 days left) | expired |
    # unknown (either input missing). Never stored.
    warranty_status: str
    warranty_end_date: date | None
    # Replaced marker — mirrors ToolPublic's exactly.
    replaced_on: date | None = None
    replaced_by_item_id: uuid.UUID | None = None
    replaced_by_name: str | None = None
    replaced_note: str = ""
    currently_in_tool_id: uuid.UUID | None
    currently_in_tool_name: str | None = None
    upc: str = ""
    quantity: int = 1
    dealer_company_id: uuid.UUID | None = None
    dealer_company_name: str | None = None
    tags: list[TagPublic] = []
    custom_data: dict
    attachments: list[AttachmentPublic]
    created_at: datetime
    updated_at: datetime
    # Entitlement standing — same contract as ToolPublic.active.
    active: bool = True


class AssetSearchItem(BaseModel):
    """One row of the unified inventory search (GET /search/all):
    a tool or a battery, marked by `item_kind`. Carries the union
    of both records' public fields; battery-only fields are null
    on tools. Extra keys pass through untouched (the serializers
    own the shapes)."""

    model_config = ConfigDict(extra="allow")

    item_kind: str  # "tool" | "battery"
    id: uuid.UUID
    name: str


# -- location tree (Package B) -------------------------------------------------
class LocationNodePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    # Drawer-grid position (audit A3): set when this node is a
    # drawer inside the layout (toolbox) node parent_layout_id
    # names; drawer_index is its position there. Both null on
    # ordinary nodes.
    parent_layout_id: uuid.UUID | None = None
    drawer_index: int | None = None
    # The node's full path ("Shop Toolbox / Left Drawer 2") — the
    # same string filed items carry as their `location` text.
    path: str = ""
    sort_order: int = 0
    # Items filed directly under this node, and under it plus its
    # whole subtree (the filter-by-place count).
    item_count: int = 0
    subtree_item_count: int = 0
    created_at: datetime
    updated_at: datetime


class LocationNodeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    sort_order: int = 0
    parent_layout_id: uuid.UUID | None = None
    drawer_index: int | None = Field(default=None, ge=0)


class LocationNodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # Tri-state via exclude_unset at the route: absent = leave the
    # parent alone; null = lift to the top tier.
    parent_id: uuid.UUID | None = None
    sort_order: int | None = None
    # Same tri-state for the drawer fields: absent = untouched,
    # null = no longer a drawer.
    parent_layout_id: uuid.UUID | None = None
    drawer_index: int | None = Field(default=None, ge=0)


class LocationNodeDelete(BaseModel):
    # Where children + items go when a non-empty node is deleted:
    # reassign_to_id moves them; detach unfiles items and lifts
    # children to the deleted node's parent. Neither = refuse.
    reassign_to_id: uuid.UUID | None = None
    detach: bool = False


# -- AI drawer lookup (2026-10-25; grounded rework same day) ---------------------
class DrawerLookupRequest(BaseModel):
    # The toolbox's make + model, entered in the lookup's OWN
    # box — the location's name the user picked is separate
    # and never read here. `query` is the original field name,
    # still accepted; `model` wins when both arrive. `link` is
    # a pasted product page: the grounded pipe reads THAT page
    # and needs no search key.
    query: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    link: str = Field(default="", max_length=2000)


class DrawerConfiguration(BaseModel):
    drawer_count: int
    extra_sections: list[str] = []


class DrawerLookupResponse(BaseModel):
    # found=false is the honest miss: no count, no source —
    # the UI falls back to manual entry and nothing is charged.
    # grounded=true means the configurations were read off a
    # real product page (named by source + source_url);
    # grounded=false is AI recall, which the UI labels
    # unverified. drawer_count / extra_sections mirror the
    # single configuration when there is exactly one; with
    # several, the choice lives in configurations.
    found: bool
    grounded: bool = False
    drawer_count: int | None = None
    source: str | None = None
    source_url: str | None = None
    configurations: list[DrawerConfiguration] = []
    extra_sections: list[str] = []
    link_error: bool = False
    charged: int = 0


# -- bulk edit (Package B) -------------------------------------------------------
class BulkItemRef(BaseModel):
    kind: str = Field(pattern="^(tool|battery)$")
    id: uuid.UUID


class BulkRequest(BaseModel):
    items: list[BulkItemRef] = Field(min_length=1, max_length=500)
    # move_location | set_dealer | set_brand | set_category |
    # add_tag | set_standing | delete — params per action, judged
    # by the service.
    action: str = Field(max_length=50)
    params: dict = {}


class BulkItemResult(BaseModel):
    kind: str
    id: str


class BulkResult(BaseModel):
    action: str
    affected: int
    items: list[BulkItemResult] = []


# -- vault statistics ------------------------------------------------------
class InventoryStats(BaseModel):
    """Owner-scoped vault totals for dashboard overviews.

    Exact semantics (all computed over ONLY the requesting owner's
    assets — tools AND batteries, which are first-class assets):

    - ``total_items``: COUNT of the owner's tools + batteries.
    - ``total_quantity``: SUM of ``quantity`` over the SAME
      population ``total_items`` counts — top-level tools (a
      set counts its own quantity once; tools attached into a
      set never add theirs) plus every battery. The physical
      unit count beside the item count (owner order,
      2026-11-10: the inventory header's stats).
    - ``total_market_value``: SUM of ``msrp`` over both kinds — the
      "today's list price" field, i.e. what each asset costs at
      current market. An asset with no msrp set contributes 0 (it is
      NOT back-filled from any other cost field). Serialized as a
      decimal string, e.g. ``"146625.00"``.
    - ``total_replacement_cost``: SUM of ``replacement_cost`` over
      both kinds; an asset with no replacement cost set contributes
      0. Decimal string.
    - ``total_value`` (deep audit F1-03): the REPORTS-basis value —
      SUM of ``purchase_price`` x quantity over both kinds, plus the
      priced addon pieces of sets (the report engine's _set_totals
      rules; a piece price is the piece's own figure and never
      rolls into any total — core pieces may carry one since the
      2026-10-25 piece-price rule (migration 0059), but only addon
      prices join a set's totals, and gone pieces never contribute).
      This is the number the Reports page prints as
      its grand "Total value", and the Home stat of the same name
      reads THIS field, so the two surfaces can never disagree
      again. (``total_market_value`` above keeps its msrp meaning;
      owners record what they paid, not list prices, so an
      msrp-only total read $0 on real vaults.)
    - ``category_count``: COUNT of DISTINCT non-empty ``category``
      values across the owner's tools and batteries (the empty-string
      default is not a category).
    - ``warranties_expiring_soon`` / ``warranties_expired`` (audit
      A6): COUNT of assets whose COMPUTED warranty standing (the
      shared warranty_status_of the item pages use) is expiring_soon
      (ends today or within 30 days) / expired, over the same
      population the money totals describe (active sets applied the
      same way; lifetime coverage never counts).

    An empty vault returns 0 / 0 / "0.00" / "0.00" / 0 / 0 / 0 — never nulls.
    """

    total_items: int
    total_quantity: int = 0
    total_market_value: Decimal
    total_value: Decimal = Decimal("0.00")
    total_replacement_cost: Decimal
    category_count: int
    warranties_expiring_soon: int = 0
    warranties_expired: int = 0


# -- QR bin labels (blueprint §18) -----------------------------------------
class LabelItemPublic(BaseModel):
    """One printable item label's data (GET /labels): exactly what
    the label face renders — name, brand/model, serial, location —
    plus the canonical path the QR code encodes. The QR payload is
    the site's origin + `qr_path`; scanning it opens the item for its
    signed-in owner and the sign-in page for everyone else (the path
    itself is meaningless without a session, so nothing leaks)."""

    kind: str  # "tool" | "battery"
    id: uuid.UUID
    name: str
    brand: str
    model: str
    serial_number: str
    location: str
    is_set: bool
    qr_path: str


class LabelSelectionPublic(BaseModel):
    """The resolved selection: labels in request order, and the
    count of requested refs that did NOT resolve (foreign, deleted,
    or malformed — deliberately indistinguishable)."""

    labels: list[LabelItemPublic]
    skipped: int


class LocationLabelPublic(BaseModel):
    """One bin/location label (GET /labels/locations): the owner's
    distinct location text and how many top-level items sit there."""

    location: str
    count: int


# -- uploads -------------------------------------------------------------
class UploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=127)
    kind: str = "photo"  # photo | document | receipt | manual
    size_bytes: int | None = Field(default=None, gt=0)


class UploadUrlResponse(BaseModel):
    upload_url: str
    key: str
    expires_in: int


class AttachRequest(BaseModel):
    key: str = Field(min_length=1)
    filename: str = ""
    # Police-report documents (wizard + inventory fixes pack,
    # 2026-10-25): when set, the file is tied to that lost/stolen
    # report on this same item — validated in attach_file, stored
    # as a marker on the attachment entry.
    loss_report_id: uuid.UUID | None = None


class AttachmentEmailRequest(BaseModel):
    """The AttachmentViewer's "Email this file" action: send one of
    the item's OWN attachments to a recipient through the email seam
    (owner-scoped + rate-limited in the service)."""

    key: str = Field(min_length=1)
    recipient: EmailStr


class AttachToSetRequest(BaseModel):
    """Attach this tool into a set as an addon (POST /{tool_id}/attach-to-set)."""

    set_id: uuid.UUID


class AttachmentEmailResponse(BaseModel):
    sent: bool
    filename: str
    kind: str
    recipient: str


# -- importer (general CSV/XLSX import) ------------------------------------
class ImportFieldPublic(BaseModel):
    key: str
    label: str
    type: str  # text | multi | tags | money | decimal | int | date | bool | dealer | custom
    required: bool = False
    custom_type: str | None = None


class ImportSessionPublic(BaseModel):
    session_id: uuid.UUID
    filename: str
    file_format: str  # csv | xlsx
    kind: str  # tool | battery
    headers: list[str]
    sample_rows: list[list[str]]
    row_count: int
    expires_at: datetime
    fields: list[ImportFieldPublic]
    # {column_index_as_string: field_key} — auto-suggestions the UI
    # pre-fills; the user can change every one of them.
    suggested_mapping: dict[str, str]


class ImportSuggestRequest(BaseModel):
    kind: str = Field(pattern="^(tool|battery)$")


class ImportSuggestResponse(BaseModel):
    kind: str
    fields: list[ImportFieldPublic]
    suggested_mapping: dict[str, str]


class ImportResolutionDecision(BaseModel):
    """One answer from the Resolve matches step (smart matching,
    2026-10-19): what to do with one distinct incoming value.
    map -> target_id (dealer/location) or target_value (brand/
    category/tag); create -> a new value (location may carry the
    parent_id to create under); unset -> drop the value."""

    action: str = Field(pattern="^(map|create|unset)$")
    target_id: uuid.UUID | None = None
    target_value: str | None = None
    parent_id: uuid.UUID | None = None


class ImportRunRequest(BaseModel):
    kind: str = Field(pattern="^(tool|battery)$")
    # {column_index_as_string: field_key | null} — columns absent or
    # null are not imported. Validated server-side: unknown fields
    # are 422s, as is a second column for a single-value field
    # (multi-value list fields may take several columns).
    mapping: dict[str, str | None] = {}
    skip_duplicates: bool = True
    # {field_key: {raw_value: decision}} — the Resolve matches
    # answers. Automatic matches (normalized-exact, learned) need
    # no entry; any value the resolve plan marks "ask" REQUIRES
    # one here, or the run refuses with a 422 naming it.
    resolutions: dict[str, dict[str, ImportResolutionDecision]] = {}


class ImportRowPreview(BaseModel):
    """What the row's multi-value data looks like AFTER merging
    and dedupe (import round, 2026-10-25): the model/serial lists
    as they will land, plus the set flag and its piece serials."""

    models: list[str] = []
    serials: list[str] = []
    is_set: bool = False
    set_serials: list[str] = []


class ImportRowResult(BaseModel):
    row: int  # spreadsheet row number (header is row 1)
    status: str  # ok | warning | error | blank
    name: str = ""
    messages: list[str] = []
    duplicate: bool = False
    preview: ImportRowPreview = ImportRowPreview()


class ImportCapInfo(BaseModel):
    enforcement: bool
    limit: int | None = None
    current_count: int | None = None
    remaining: int | None = None
    would_exceed: int = 0


class ImportResolveRequest(BaseModel):
    kind: str = Field(pattern="^(tool|battery)$")
    mapping: dict[str, str | None] = {}


class ImportTargetPublic(BaseModel):
    target_id: uuid.UUID | None = None
    target_value: str | None = None
    label: str
    score: float | None = None


class ImportResolutionPublic(BaseModel):
    action: str  # map | create | unset
    target_id: uuid.UUID | None = None
    target_value: str | None = None
    parent_id: uuid.UUID | None = None


class ImportResolveEntryPublic(BaseModel):
    field: str  # dealer_name | brand | category | tags | location
    raw: str
    rows: int
    status: str  # auto | ask
    source: str | None = None  # exact | learned (auto entries)
    resolution: ImportResolutionPublic | None = None
    candidates: list[ImportTargetPublic] = []


class ImportResolveResponse(BaseModel):
    entries: list[ImportResolveEntryPublic]
    # The full "pick a different one" list per field.
    options: dict[str, list[ImportTargetPublic]] = {}
    unresolved: int = 0


class ImportMappingApplied(BaseModel):
    """One mapping a run applied, listed in the dry run and the
    final summary — silent matches included (nothing invisible)."""

    field: str
    raw: str
    rows: int
    action: str  # map | create | unset
    target_label: str = ""
    source: str  # exact | learned | decision


class ImportDryRunPublic(BaseModel):
    session_id: uuid.UUID
    kind: str
    total_rows: int
    counts: dict[str, int]
    importable: int
    cap: ImportCapInfo
    rows: list[ImportRowResult]
    mappings: list[ImportMappingApplied] = []


class ImportErrorRow(BaseModel):
    row: int
    messages: list[str] = []


class ImportSummaryPublic(BaseModel):
    kind: str
    imported: int
    skipped_duplicates: int
    skipped_over_cap: int
    over_cap_rows: list[int] = []
    errors: int
    error_rows: list[ImportErrorRow] = []
    total_rows: int
    mappings: list[ImportMappingApplied] = []


class LearnedMappingPublic(BaseModel):
    """One remembered Resolve answer (Settings → Import matching)."""

    id: uuid.UUID
    field: str
    raw_value: str
    action: str  # map | create | unset
    target_id: uuid.UUID | None = None
    target_value: str | None = None
    target_label: str = ""
    updated_at: datetime


# -- custom field definitions --------------------------------------------
class FieldDefinitionCreate(BaseModel):
    item_type: str = "tool"
    name: str = Field(min_length=1, max_length=100)  # slug: "vin"
    label: str = Field(min_length=1, max_length=200)  # "VIN"
    field_type: str = "text"  # text | number | date | dropdown | boolean
    required: bool = False
    searchable: bool = True
    options: list[str] = []
    sort_order: int = 0


class FieldDefinitionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    field_type: str | None = None
    required: bool | None = None
    searchable: bool | None = None
    options: list[str] | None = None
    sort_order: int | None = None


class FieldDefinitionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_type: str
    name: str
    label: str
    field_type: str
    required: bool
    searchable: bool
    options: list[str]
    sort_order: int
    created_at: datetime


# SetPieceInline is defined below the tool schemas (it extends
# SetPieceCreate); resolve their quoted forward references now that
# the name exists.
ToolCreate.model_rebuild()
ToolUpdate.model_rebuild()


# -- categories (manager, gap wave 1) --------------------------------------------
class CategoryPublic(BaseModel):
    name: str
    item_count: int = 0
    # True when a registry row anchors the category (it can exist
    # with zero items); False for a name that only lives on items.
    registered: bool = False
    # Starred (owner spec 2026-10-24): the owner's shortcut set —
    # starred categories appear as links in the Inventory view
    # row. Only a registry row can carry the flag; starring a
    # name that lives only on items registers it first.
    starred: bool = False
    # Create-only signal: the caller asked for the category to
    # be born starred but the 5-star cap was already full, so
    # it was created UNSTARRED (the cap blocks the star, never
    # the category). Always False outside create responses.
    star_capped: bool = False
    # Preinstalled starter (owner spec 2026-10-25): one of the
    # four seeded categories every account carries. Starters
    # can't be deleted; `system_key` says which one it is
    # ("batteries" is also fixed-name). None/False for the
    # owner's own categories.
    preinstalled: bool = False
    system_key: str | None = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Born starred (owner steer 2026-10-24): create + star in
    # one step; the cap degrades this to an unstarred create
    # with star_capped=True rather than refusing the category.
    starred: bool = False


class CategoryStar(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    starred: bool


class CategoryRename(BaseModel):
    old_name: str = Field(min_length=1, max_length=200)
    new_name: str = Field(min_length=1, max_length=200)


class CategoryMerge(BaseModel):
    source_name: str = Field(min_length=1, max_length=200)
    target_name: str = Field(min_length=1, max_length=200)


class CategoryDelete(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CategoryDeleteResult(BaseModel):
    detached: int


class CategoryMergeResult(CategoryPublic):
    moved: int = 0


# -- lost/stolen reports (gap wave 1) ---------------------------------------------
class LossReportCreate(BaseModel):
    standing: str = Field(pattern="^(lost|stolen)$")
    reported_date: date | None = None
    police_report_number: str = Field(default="", max_length=100)
    police_department: str = Field(default="", max_length=200)
    insurer_name: str = Field(default="", max_length=200)
    claim_number: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=5000)


class LossReportUpdate(BaseModel):
    reported_date: date | None = None
    police_report_number: str | None = Field(default=None, max_length=100)
    police_department: str | None = Field(default=None, max_length=200)
    insurer_name: str | None = Field(default=None, max_length=200)
    claim_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)


class LossReportRecover(BaseModel):
    recovered_date: date | None = None


class LossReportPublic(BaseModel):
    id: uuid.UUID
    item_kind: str
    item_id: uuid.UUID
    status: str
    standing: str
    reported_date: date | None = None
    police_report_number: str = ""
    police_department: str = ""
    insurer_name: str = ""
    claim_number: str = ""
    notes: str = ""
    recovered_date: date | None = None
    created_at: datetime
    updated_at: datetime
    # Documents tied to THIS report (the item's attachments whose
    # loss_report_id marker names it) — filled by the per-item
    # list read; empty on the single-report writes.
    documents: list[AttachmentPublic] = []


# -- asset history (2026-10-20) ----------------------------------------------------
class MarkReplacedRequest(BaseModel):
    """Mark-replaced payload: the date defaults to today
    server-side when omitted; the replacement item and note are
    both optional (a swap with no successor recorded is a
    legitimate story — the old record just ends)."""

    replaced_on: date | None = None
    replaced_by_item_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=1000)


class HistoryEventPublic(BaseModel):
    ts: datetime
    # created | purchased | edited | standing | replaced |
    # repair | service | lent | returned | claim | lost |
    # recovered | warranty (the frontend maps each to an icon)
    kind: str
    title: str
    detail: str = ""
    link: str | None = None


class ItemHistoryPublic(BaseModel):
    item_kind: str
    item_id: uuid.UUID
    events: list[HistoryEventPublic] = []


# -- health check (gap wave 1) ------------------------------------------------------
class HealthCheckPiece(BaseModel):
    """One set piece missing its serial number, with the piece's
    own id — the health check's Fix-it deep link lands on THAT
    piece's serial field in the set's edit form (2026-11-05)."""

    id: uuid.UUID
    name: str


class HealthCheckItem(BaseModel):
    kind: str
    id: uuid.UUID
    name: str
    # Subset of: identifier | photo | purchase_date. ("identifier"
    # = the item has NEITHER a model nor a serial number; either
    # one alone satisfies it — owner ruling 2026-11-03.)
    missing: list[str] = []
    # Names of the set's present pieces missing a serial number
    # (the piece rule: pieces surface under their set).
    pieces_missing_serial: list[str] = []
    # The same pieces as {id, name} pairs, for deep links.
    pieces_missing: list[HealthCheckPiece] = []
    # A9 guidance flag (same rule as the item pages).
    sub_limit_warning: bool = False
    # Sweep E3 (busy-work #5): this item's missing photo is
    # currently ignored (photo_ignored=True only ever rides an
    # item flagged for OTHER gaps — a photo-only item drops off
    # the list entirely and is named in photo_ignored_items).
    photo_ignored: bool = False
    # Identifying data for the fix-all wizard's steps (sweep E3):
    # the item's brand and its primary model / serial numbers as
    # recorded (empty strings when unset — the identifier gap is
    # exactly the both-empty case).
    brand: str = ""
    model: str = ""
    serial_number: str = ""


class HealthCheckPhotoIgnoredItem(BaseModel):
    """One active item whose missing photo is currently ignored
    (sweep E3): reversal data for the Health Check page only —
    the due widget's payload deliberately does not carry it."""

    kind: str
    id: uuid.UUID
    name: str


class HealthCheckPublic(BaseModel):
    total: int
    counts: dict[str, int]
    items: list[HealthCheckItem] = []
    # Sweep B2-F16: active items scanned (see service.health_check).
    total_items: int = 0
    # Sweep E3: items whose missing photo is ignored (see
    # service.health_check) — never counted in total/counts.
    photo_ignored_items: list[HealthCheckPhotoIgnoredItem] = []


class HealthPhotoIgnoreRequest(BaseModel):
    """Set/clear one item's photo ignore (sweep E3). There is no
    field choice: the ignore is photo-only by construction."""

    kind: str = Field(pattern="^(tool|battery)$")
    item_id: uuid.UUID
    ignored: bool


class HealthPhotoIgnorePublic(BaseModel):
    kind: str
    id: uuid.UUID
    name: str
    photo_ignored: bool


class HealthPhotoIgnoreAllPublic(BaseModel):
    """The bulk photo-ignore's answer (owner order, 2026-11-12):
    how many items were NEWLY ignored by this one action —
    already-ignored and photo-having items never count."""

    ignored_count: int


class HealthCheckDueItem(HealthCheckItem):
    """One flagged item as the Health checks due widget reads
    it: the scan's own row plus its primary photo's rendition
    URLs (null when the item has no photo — a missing photo is
    one of the gaps the scan flags). Display data only; the
    gap computation is the scan's, unchanged."""

    thumb_url: str | None = None
    thumb_url_sm: str | None = None


class HealthCheckDuePublic(BaseModel):
    total: int
    counts: dict[str, int]
    items: list[HealthCheckDueItem] = []


# -- sold tracking (wave 2, 2026-10-20) ---------------------------------------------
class MarkSoldRequest(BaseModel):
    """quantity_sold omitted = the WHOLE quantity (a full sale).
    Less than the item's quantity is a partial sale of that many
    units. sale_price is the TOTAL for the units sold."""

    quantity_sold: int | None = Field(default=None, ge=1)
    buyer_name: str = Field(default="", max_length=200)
    buyer_contact: str = Field(default="", max_length=300)
    sale_price: MoneyValue
    sold_on: date | None = None
    note: str = Field(default="", max_length=1000)


class SaleRecordPublic(BaseModel):
    id: uuid.UUID
    item_kind: str
    item_id: uuid.UUID
    set_id: uuid.UUID | None
    item_name: str
    quantity_sold: int
    buyer_name: str
    buyer_contact: str
    sale_price: Decimal
    sold_on: date
    note: str
    source: str
    kind: str
    reverses_id: uuid.UUID | None
    # Derived at read time: a sale with a compensating reversal
    # row is history, not a live sale.
    reversed: bool = False
    created_at: datetime


class SalesTotalsPublic(BaseModel):
    total_sold_value: Decimal
    sale_count: int
    units_sold: int
    record_count: int


class PosterPick(BaseModel):
    item_kind: str = Field(pattern="^(tool|battery)$")
    item_id: uuid.UUID
    # The ASKING price printed on the poster — not the item's
    # purchase price (an owner sells at their own figure).
    price: MoneyValue | None = Field(default=None)
    # When the item also has a live marketplace listing, the QR
    # points at the listing; otherwise at the seller's public
    # profile. Supplied by the caller — there are no public item
    # pages to derive one from.
    listing_url: str = Field(default="", max_length=1000)


class PosterRequest(BaseModel):
    items: list[PosterPick] = Field(min_length=1, max_length=50)
