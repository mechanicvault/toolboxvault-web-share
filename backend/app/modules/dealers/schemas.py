"""Dealers DTOs."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PhoneEntry(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    number: str = Field(min_length=1, max_length=100)


class WarrantyProcess(BaseModel):
    """The brand's warranty route when there is no simple mail-in:
    `gate` is the required first step (call / form / photo claim /
    return to store); `notes` are short researched process facts."""

    gate: str | None = None
    notes: list[str] = Field(default_factory=list, max_length=24)


class PersonalEditInfo(BaseModel):
    """The viewer's personal layer over a DIRECTORY company
    (2026-11-05): present (non-null) on a CompanyView exactly
    when the VIEWER has personal edits for the company, naming
    the fields he overrode. The view's field values are already
    his effective ones; this marker is what lets the UI say
    "edited by you" and offer Reset honestly. Always None for
    raw serializations (admin curation, signed-out-shaped
    reads) and for the viewer's own companies."""

    fields: list[str] = Field(default_factory=list)


class CompanyView(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    website: str
    address: str
    phones: list[PhoneEntry]
    notes: str
    is_directory: bool
    is_mine: bool
    personal_edit: PersonalEditInfo | None = None
    # Corporate directory data (2026-10-19): warranty-service facts
    # from official brand sources. ship_to_* is None unless the
    # brand publishes a warranty mail-in address; scoped addresses
    # always carry their scope note.
    kind: str = "manufacturer"
    warranty_url: str = ""
    official_flyer_url: str = ""
    warranty_phone: str | None = None
    customer_service_phone: str | None = None
    ship_to_name: str | None = None
    ship_to_address: str | None = None
    ship_to_scope: str | None = None
    ship_to_scope_note: str | None = None
    warranty_process: WarrantyProcess | None = None
    logo_key: str | None = None
    logo_url: str | None = None
    logo_tile: str | None = None
    created_at: datetime
    updated_at: datetime


class PersonalCompanyWrite(BaseModel):
    """The personal-edit payload (2026-11-05): the identity /
    contact subset of CompanyWrite — the fields a viewer may
    keep as HIS details for a directory dealer. The corporate
    warranty block is deliberately absent: it is researched
    directory data, not the viewer's to restate. Constraints
    mirror CompanyWrite field for field; the service runs the
    merged result through the same cleaner the company form
    uses, so validation can never drift between the two."""

    name: str = Field(min_length=1, max_length=300)
    email: str = Field(default="", max_length=320)
    website: str = Field(default="", max_length=500)
    address: str = Field(default="", max_length=5000)
    phones: list[PhoneEntry] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=5000)
    logo_key: str | None = Field(default=None, max_length=500)
    logo_tile: str | None = Field(default=None, max_length=20)


class CompanyWrite(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    email: str = Field(default="", max_length=320)
    website: str = Field(default="", max_length=500)
    address: str = Field(default="", max_length=5000)
    phones: list[PhoneEntry] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=5000)
    kind: str = Field(default="manufacturer", max_length=20)
    warranty_url: str = Field(default="", max_length=500)
    official_flyer_url: str = Field(default="", max_length=500)
    warranty_phone: str | None = Field(default=None, max_length=100)
    ship_to_name: str | None = Field(default=None, max_length=300)
    ship_to_address: str | None = Field(default=None, max_length=2000)
    ship_to_scope: str | None = Field(default=None, max_length=20)
    ship_to_scope_note: str | None = Field(default=None, max_length=2000)
    warranty_process: WarrantyProcess | None = None
    logo_key: str | None = Field(default=None, max_length=500)
    logo_tile: str | None = Field(default=None, max_length=20)


class PrivateAgentView(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID | None
    company_name: str
    name: str
    phone: str
    email: str
    notes: str
    # Private -> platform switch (dealer portal): an archived record
    # was linked to a platform account; the number is the account it
    # linked to (the owner's own record — showing it is safe).
    archived: bool = False
    linked_account_number: str | None = None
    # Agent code + takeover (2026-11-03): the record's own code
    # (owner-only views render this serializer), grouped for
    # humans; link_source says how a link came to be ("takeover" |
    # "switch" | None); claimed_by_* names the agent who took the
    # record over, for the owner's claimed state.
    agent_code: str = ""
    agent_code_display: str = ""
    link_source: str | None = None
    claimed_by_name: str | None = None
    claimed_by_account_number: str | None = None
    # The record fields (stage 1, 2026-11-04): route area, the
    # route schedule triple (frequency words are weekly /
    # biweekly / monthly; all None = no route), tenure dates.
    location: str = ""
    route_frequency: str | None = None
    route_day_of_week: int | None = None
    route_anchor_date: date | None = None
    started_at: date | None = None
    ended_at: date | None = None
    created_at: datetime
    updated_at: datetime


class TakeoverEnterCode(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class TakeoverEnterResult(BaseModel):
    # pending | already_claimed | own_record
    status: str
    agent_name: str
    company_name: str
    company_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID
    request_id: uuid.UUID | None = None


class TakeoverRequestView(BaseModel):
    id: uuid.UUID
    requester_name: str
    requester_account_number: str
    created_at: datetime


class MyTakeoverRequestView(BaseModel):
    id: uuid.UUID
    # pending | accepted | declined | superseded
    status: str
    agent_name: str
    company_name: str
    company_id: uuid.UUID | None = None
    owner_name: str
    created_at: datetime
    decided_at: datetime | None = None


class ClaimedRecordView(BaseModel):
    private_agent_id: uuid.UUID
    agent_name: str
    company_id: uuid.UUID | None = None
    company_name: str
    owner_name: str
    claimed_at: datetime


class TakeoverMineView(BaseModel):
    """The agent-side card: my code-entry asks and the customer
    records I have taken over."""

    requests: list[MyTakeoverRequestView]
    claimed: list[ClaimedRecordView]


class PrivateAgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    company_id: uuid.UUID | None = None
    phone: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=320)
    notes: str = Field(default="", max_length=5000)
    location: str = Field(default="", max_length=300)
    route_frequency: str | None = Field(default=None, max_length=20)
    route_day_of_week: int | None = None
    route_anchor_date: date | None = None
    started_at: date | None = None
    ended_at: date | None = None


class PrivateAgentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    company_id: uuid.UUID | None = None
    phone: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=300)
    route_frequency: str | None = Field(default=None, max_length=20)
    route_day_of_week: int | None = None
    route_anchor_date: date | None = None
    started_at: date | None = None
    ended_at: date | None = None


# -- contact cards: vCard import into private agents (agent card
# import lane, 2026-11-07) ----------------------------------------
#
# Import NEVER writes blind and NEVER touches a platform agent:
# the preview parses the uploaded file, suggests the dealer each
# card's ORG points at, and flags likely duplicates against the
# caller's OWN private records per dealer; the confirm creates
# exactly the rows it is handed, each through the ordinary
# private-agent create path.


class AgentImportDuplicate(BaseModel):
    """One company under which a matching private record already
    sits in the caller's book (same collapsed name AND a shared
    phone or email). The modal re-derives the row's badge from
    this list when the dealer pick changes."""

    company_id: uuid.UUID
    company_name: str
    duplicate_of: str


class AgentImportPreviewRow(BaseModel):
    index: int
    name: str
    phone: str = ""
    email: str = ""
    org: str = ""
    location: str = ""
    notes: str = ""
    # The dealer the card's ORG matched (exact name match
    # against the companies the caller can see), or None — the
    # caller picks; nothing is ever created dealerless.
    suggested_company_id: uuid.UUID | None = None
    suggested_company_name: str | None = None
    # The duplicate state FOR the suggested dealer (the modal
    # re-derives it from `duplicates` when the pick changes).
    duplicate: bool = False
    duplicate_of: str | None = None
    duplicates: list[AgentImportDuplicate] = []


class AgentImportPreviewError(BaseModel):
    index: int
    message: str


class AgentImportPreview(BaseModel):
    rows: list[AgentImportPreviewRow] = []
    errors: list[AgentImportPreviewError] = []
    total_cards: int = 0


class AgentImportRow(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    company_id: uuid.UUID
    phone: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=320)
    location: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=5000)


class AgentImportRequest(BaseModel):
    # The rows the owner confirmed in the preview — created
    # verbatim through the ordinary private-agent create path.
    agents: list[AgentImportRow] = Field(max_length=500)


class AgentImportResult(BaseModel):
    created: list[PrivateAgentView] = []
    count: int = 0


class PreferredAgentView(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    # platform | private
    kind: str
    agent_user_id: uuid.UUID | None
    private_agent_id: uuid.UUID | None
    name: str
    phone: str
    email: str
    account_number: str | None
    # The row is a CONNECTION; is_preferred marks A preferred
    # agent for (user, company) — any number of rows may carry
    # it (multi-preferred, 2026-11-05). Tenure reads off the
    # record for private rows, off the connection for platform
    # rows (see service.serialize_preferred).
    is_preferred: bool = False
    tenure_started_at: date | None = None
    tenure_ended_at: date | None = None
    created_at: datetime
    # His next route day from his route schedule (the roster's
    # computation), or None when he has no complete schedule.
    next_visit: date | None = None


class PreferredSummaryView(BaseModel):
    """The preferred-agent SUMMARY for one company (owner
    ruling 2026-11-06): how a display names the caller's
    preferred agent — "none" (no connection at all), "one"
    (exactly one preferred agent; `agent` carries him), or
    "many" (more than one preferred agent; `agent` is None —
    displays show no specifics, just a "Multiple Agents" link
    to the dealer's Agents tab). With connections but NONE
    flagged, the standing fallback resolves the earliest row
    as "one", exactly as displays behaved before the flag."""

    # none | one | many
    state: str
    agent: PreferredAgentView | None = None


# ---------------------------------------------------------------------
# The roster + agent record (stage 1, 2026-11-04)
# ---------------------------------------------------------------------


class RosterEntryView(BaseModel):
    """One seat on a company's roster: a private record of the
    viewer's, or a platform agent he is connected with."""

    # "private:<record id>" | "platform:<user id>"
    key: str
    # private | platform
    kind: str
    connection_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID | None = None
    agent_user_id: uuid.UUID | None = None
    name: str
    phone: str = ""
    email: str = ""
    account_number: str | None = None
    # Route area: the record's location, or the profile's
    # service area for a platform agent.
    location: str = ""
    route_frequency: str | None = None
    route_day_of_week: int | None = None
    route_anchor_date: date | None = None
    next_visit: date | None = None
    started_at: date | None = None
    ended_at: date | None = None
    is_preferred: bool = False
    claimed_by_name: str | None = None
    claimed_by_account_number: str | None = None


class RosterClaimView(BaseModel):
    id: uuid.UUID
    claim_number: str
    status: str
    is_open: bool
    item_name: str = ""
    created_at: datetime


class RosterTruckView(BaseModel):
    id: uuid.UUID
    status: str
    balance: str
    agent_name: str = ""
    # Stage 2 (2026-11-05): the slot's schedule facts — next
    # due + the computed missed state (service._truck_slot).
    next_due_date: date | None = None
    payment_amount: Decimal | None = None
    missed_payments: int = 0
    amount_past_due: Decimal = Decimal("0")


class RosterAgentDetailView(BaseModel):
    entry: RosterEntryView
    # The full private record (owner's view) for private seats;
    # None for platform seats (their facts ride on the entry).
    record: PrivateAgentView | None = None
    notes: str = ""
    claims: list[RosterClaimView] = Field(default_factory=list)
    truck_accounts: list[RosterTruckView] = Field(default_factory=list)
    can_delete: bool = False
    delete_block_reason: str | None = None


class SetAgentPreferredRequest(BaseModel):
    company_id: uuid.UUID
    private_agent_id: uuid.UUID | None = None
    agent_user_id: uuid.UUID | None = None
    # Star (true) or unstar (false) this ONE agent — per-agent
    # and independent (multi-preferred, 2026-11-05).
    is_preferred: bool


class PreferredAgentCreate(BaseModel):
    company_id: uuid.UUID
    private_agent_id: uuid.UUID | None = None
    # Platform agents link by EXACT account number only.
    agent_account_number: str | None = Field(default=None, max_length=32)


# ---------------------------------------------------------------------
# Dealer portal (agent profiles, representations, public cards)
# ---------------------------------------------------------------------


class AgentProfileView(BaseModel):
    display_name: str
    phone: str
    contact_email: str
    service_area: str
    bio: str
    photo_url: str | None
    has_photo: bool
    publicly_listed: bool
    # Service-area geometry (dealer build): the territory the map
    # editor works on. area_polygon is the stored GeoJSON Polygon;
    # radius areas read center + miles.
    has_area: bool = False
    area_type: str | None = None
    area_polygon: dict | None = None
    area_center_lat: float | None = None
    area_center_lng: float | None = None
    area_radius_miles: float | None = None
    area_zip: str = ""
    # Route schedule (audit A2): the three facts + the computed
    # next visit (ISO date; null when no complete schedule).
    route_frequency: str | None = None
    route_day_of_week: int | None = None
    route_anchor_date: date | None = None
    route_next_visit: date | None = None


class AgentProfileWrite(BaseModel):
    display_name: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=100)
    contact_email: str | None = Field(default=None, max_length=320)
    service_area: str | None = Field(default=None, max_length=300)
    bio: str | None = Field(default=None, max_length=5000)
    publicly_listed: bool | None = None
    # Area write (dealer build): present area_type selects the
    # shape — "polygon" reads area_polygon, "radius" reads
    # center + area_radius_miles (+ area_zip), null clears the
    # area. Absent area_type leaves the area untouched.
    area_type: str | None = Field(default=None, max_length=20)
    area_polygon: dict | None = None
    area_center_lat: float | None = None
    area_center_lng: float | None = None
    area_radius_miles: float | None = None
    area_zip: str | None = Field(default=None, max_length=10)
    # Route write (audit A2): present fields replace; explicit
    # nulls clear. Frequency must be one of the three cycles.
    route_frequency: str | None = Field(
        default=None, pattern="^(weekly|biweekly|monthly)$"
    )
    route_day_of_week: int | None = Field(default=None, ge=0, le=6)
    route_anchor_date: date | None = None


class PhotoUploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=300)
    content_type: str = Field(min_length=1, max_length=120)
    size_bytes: int | None = Field(default=None, ge=1)


class PhotoUploadUrlResponse(BaseModel):
    upload_url: str
    key: str
    expires_in: int


class PhotoAttachRequest(BaseModel):
    key: str = Field(min_length=1, max_length=500)
    filename: str | None = Field(default=None, max_length=300)


class RepresentationView(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    verified: bool
    created_at: datetime


class RepresentationCreate(BaseModel):
    company_id: uuid.UUID


class RepresentationAdminView(BaseModel):
    id: uuid.UUID
    agent_user_id: uuid.UUID
    agent_name: str
    agent_email: str
    agent_account_number: str
    company_id: uuid.UUID
    company_name: str
    verified: bool
    verified_at: datetime | None
    created_at: datetime


class RepresentationVerify(BaseModel):
    verified: bool


class PublicAgentCard(BaseModel):
    """A listed agent on a company page. Optional keys are ABSENT
    when the agent left the field empty — the serializer omits
    them, and this model is only used with exclude_none-style
    dicts built by the portal service (see routes)."""

    agent_user_id: uuid.UUID
    display_name: str
    verified: bool
    service_area: str | None = None
    bio: str | None = None
    phone: str | None = None
    contact_email: str | None = None
    photo_url: str | None = None


class CompanyDetailView(BaseModel):
    company: CompanyView
    agents: list[PublicAgentCard]
    my_preferred_agents: list[PreferredAgentView]


class PreferredByAgentCreate(BaseModel):
    company_id: uuid.UUID
    agent_user_id: uuid.UUID


class PreferredAddResult(BaseModel):
    created: bool
    preferred: PreferredAgentView


class PrivateAgentLink(BaseModel):
    # The switch links by EXACT account number only — same door as
    # platform preferred agents.
    agent_account_number: str = Field(min_length=1, max_length=32)


class DealerPortalStats(BaseModel):
    preferred_by_count: int
    companies_represented_count: int
    # "Public" | "Private" — display-ready for the home stat card.
    profile_visibility: str


# ---------------------------------------------------------------------
# Find an Agent + warranty requests (dealer build, 2026-10-20)
# ---------------------------------------------------------------------


class FindAgentCompany(BaseModel):
    company_id: uuid.UUID
    company_name: str
    verified: bool


class FindAgentCard(BaseModel):
    """One Find-an-Agent result. Contact keys exist ONLY on the
    signed-in card and ONLY when the agent published them — the
    anonymous card never carries them (built as raw dicts in
    areas.find_agent_card; this model shapes the signed-in one)."""

    agent_user_id: uuid.UUID
    display_name: str
    service_area: str = ""
    area_type: str | None = None
    verified: bool = False
    companies: list[FindAgentCompany] = Field(default_factory=list)
    photo_url: str | None = None
    phone: str | None = None
    contact_email: str | None = None


class FindAgentPoint(BaseModel):
    lat: float
    lng: float
    display_name: str


class GeocodeResult(BaseModel):
    lat: float
    lng: float
    display_name: str


class WarrantyRequestCreate(BaseModel):
    claim_id: uuid.UUID


class WarrantyStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=20)


class WarrantyAgentRef(BaseModel):
    user_id: uuid.UUID
    display_name: str


class WarrantyRequestView(BaseModel):
    id: uuid.UUID
    status: str
    status_label: str
    company_id: uuid.UUID | None
    company_name: str
    claim_id: uuid.UUID
    item_kind: str
    item_id: uuid.UUID
    item_name: str
    brand: str
    model: str
    serials: list[str] = Field(default_factory=list)
    problem: str
    purchase_date: str | None
    warranty_status: str
    requester_id: uuid.UUID
    requester_name: str
    requester_email: str
    requester_phone: str
    requester_area: str
    requester_deleted: bool
    routed_agents: list[WarrantyAgentRef] = Field(default_factory=list)
    claimed_by: WarrantyAgentRef | None = None
    claimed_by_me: bool = False
    mine: bool = False
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class WarrantyEligibility(BaseModel):
    """The repair-panel dealer box: is a send possible, and with
    exactly what payload. `payload` is present only when a send
    can happen; `existing_request` when one exists for the record."""

    available: bool
    reason: str = ""
    company_name: str = ""
    has_preferred_agent: bool = False
    preferred_agent_names: list[str] = Field(default_factory=list)
    registered_agent_count: int = 0
    payload: dict | None = None
    existing_request: WarrantyRequestView | None = None


class WarrantyCounts(BaseModel):
    incoming_unclaimed: int
    claimed_open: int
    resolved: int


# ---------------------------------------------------------------------
# Dealer intermingling (2026-10-25): the viewer's OWN records for
# one company — their items from this dealer, honest stats, and
# their claims touching it. Owner-scoped end to end; nothing here
# is ever public directory data.
# ---------------------------------------------------------------------


class CompanyItemPhoto(BaseModel):
    # The item's primary photo renditions (tile 320 / row 128).
    # Absent (None on the ref) when the item has no photo — the
    # client paints the shared no-photo placeholder instead.
    thumb_url: str | None = None
    thumb_url_sm: str | None = None


class CompanyItemRef(BaseModel):
    id: uuid.UUID
    item_kind: str  # "tool" | "battery"
    name: str
    brand: str = ""
    model: str = ""
    # The item's serial(s), flattened — the claim picker's search
    # matches on it (2026-11-03).
    serial: str = ""
    standing: str = ""
    quantity: int = 1
    is_set: bool = False
    purchase_date: date | None = None
    photo: CompanyItemPhoto | None = None
    # The item's extended purchase total (unit price x quantity;
    # a set at its full bundle total) — the same figure the
    # inventory rows display. None when no price is recorded.
    spent: Decimal | None = None


class CompanyClaimRef(BaseModel):
    id: uuid.UUID
    claim_number: str
    # Which section owns the claim (separation, 2026-11-04): the
    # dealer page carries both kinds as factual records and links
    # each row into its own section.
    kind: str
    status: str
    insurer_name: str
    incident_type: str
    incident_date: date | None = None
    total_amount: Decimal = Decimal("0")
    created_at: datetime
    # Dealer page pass (2026-11-06): the claim rows' date and
    # last-update columns.
    reported_at: datetime | None = None
    updated_at: datetime | None = None
    archived: bool = False
    items: list[str] = []


class CompanyClaimsBlock(BaseModel):
    current: list[CompanyClaimRef] = []
    history: list[CompanyClaimRef] = []


class CompanyRecordsStats(BaseModel):
    items_count: int = 0
    # Sum of the recorded purchase totals below — items without a
    # recorded price add nothing; never estimated.
    total_spent: Decimal = Decimal("0")
    # Sum of recorded replacement values; None when NO item from
    # this dealer carries one (a $0 here would be a lie).
    replacement_value: Decimal | None = None
    last_purchase_date: date | None = None
    # Claim counts ride along only when the claims module is on
    # for the viewer; None = the claims areas don't exist for them.
    open_claims: int | None = None
    total_claims: int | None = None


class CompanyMyRecordsView(BaseModel):
    items: list[CompanyItemRef] = []
    stats: CompanyRecordsStats
    # None when the claims module isn't effective for the viewer:
    # the dealer page then shows no claims areas at all.
    claims: CompanyClaimsBlock | None = None


# ---------------------------------------------------------------------
# My dealer list (owner directive, 2026-10-31): the per-user
# customization of the prefilled dealer pick list — directory
# brands the user removed from their list, plus their own entries.
# ---------------------------------------------------------------------


class DealerListEntryView(BaseModel):
    id: uuid.UUID
    name: str
    kind: str = "manufacturer"
    email: str
    website: str
    address: str
    phones: list[PhoneEntry]
    notes: str
    # Set once the entry has been picked and minted its company;
    # the company is the record from then on.
    created_company_id: uuid.UUID | None = None
    created_company_name: str = ""
    created_at: datetime
    updated_at: datetime


class DealerListEntryWrite(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: str = Field(default="manufacturer", max_length=20)
    email: str = Field(default="", max_length=320)
    website: str = Field(default="", max_length=500)
    address: str = Field(default="", max_length=5000)
    phones: list[PhoneEntry] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=5000)


class DealerPickListView(BaseModel):
    companies: list[CompanyView]
    entries: list[DealerListEntryView]


class DirectoryListState(BaseModel):
    company: CompanyView
    hidden: bool


class DealerListSettingsView(BaseModel):
    directory: list[DirectoryListState]
    entries: list[DealerListEntryView]


class DirectoryHideRequest(BaseModel):
    company_id: uuid.UUID


class DealerListRestoreResult(BaseModel):
    hidden_removed: int
    entries_removed: int
    settings: DealerListSettingsView
