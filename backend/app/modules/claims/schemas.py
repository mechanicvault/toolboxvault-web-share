"""Claims HTTP schemas: guarded payloads in, views out.

The vocabularies (incident types, statuses, target kinds, value
bases, channels) are enforced here at the boundary with pattern
constraints; the service enforces the state machine and every
money rule.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

_INCIDENT = "^(theft|loss|damage|fire|other)$"
# Both kinds' statuses: the insurance ladder plus the warranty
# ladder (overhaul, 2026-11-06: Ryan's 8 statuses — four keys
# kept, four added; "closed" stays in the vocabulary because it
# is still the insurance terminal AND the warranty close action's
# target, even though a warranty claim's status never holds it).
# The service's per-kind state machines decide which moves are
# legal — this pattern only bounds the vocabulary.
_STATUS = (
    "^(draft|filed|in_review|approved|denied|paid|closed"
    "|not_reported|reported|in_repair|completed"
    "|waiting_on_agent|waiting_on_parts|agent_has_tool|backordered)$"
)
_TARGET_KIND = "^(tool|battery|set|piece)$"
# Claim money is PURCHASE COST (owner ruling, 2026-11-06): a new
# line prices from what the owner paid ("purchase") or carries the
# owner's own figure ("entered"). "replacement" / "msrp" survive
# only as stored history on lines priced before the ruling — the
# read shapes pass value_basis through untouched.
_VALUE_BASIS = "^(purchase|entered)$"
_CHANNEL = "^(phone|email|mail|portal|in_person|other)$"
_ATTACHMENT_KIND = "^(photo|document|receipt)$"


class ClaimCreate(BaseModel):
    """The header facts at birth — all optional; the wizard opens
    an empty draft and fills it in step by step.

    Insurance (Package C): insurer_name / policy_number / the
    agent block default from the owner's My Insurance profile when
    the create leaves them blank (service-side pre-fill); values
    sent here always win. The agent fields are a SNAPSHOT — what
    lands on the claim stays on the claim."""

    insurer_name: str = Field(default="", max_length=300)
    policy_number: str = Field(default="", max_length=200)
    agent_name: str = Field(default="", max_length=300)
    agent_phone: str = Field(default="", max_length=60)
    agent_email: str = Field(default="", max_length=320)
    incident_type: str = Field(default="other", pattern=_INCIDENT)
    incident_date: date | None = None
    description: str = Field(default="", max_length=20000)
    police_report_number: str = Field(default="", max_length=200)
    police_department: str = Field(default="", max_length=300)
    police_report_date: date | None = None
    proof_of_loss_due: date | None = None
    depreciation_deadline: date | None = None


class ClaimUpdate(BaseModel):
    """Partial update; unset fields stay. Incident fields are
    draft-only (service-enforced), the rest editable until close.
    Kind-scoped in the service (2026-10-31): the insurance fields
    land only on insurance claims; manufacturer_case_number only
    on warranty claims."""

    insurer_name: str | None = Field(default=None, max_length=300)
    policy_number: str | None = Field(default=None, max_length=200)
    # Warranty claims: the manufacturer's claim / case number.
    manufacturer_case_number: str | None = Field(default=None, max_length=200)
    # The claim's own agent snapshot is editable while the claim
    # runs (typos happen) — editing it never touches the profile.
    agent_name: str | None = Field(default=None, max_length=300)
    agent_phone: str | None = Field(default=None, max_length=60)
    agent_email: str | None = Field(default=None, max_length=320)
    incident_type: str | None = Field(default=None, pattern=_INCIDENT)
    incident_date: date | None = None
    description: str | None = Field(default=None, max_length=20000)
    police_report_number: str | None = Field(default=None, max_length=200)
    police_department: str | None = Field(default=None, max_length=300)
    police_report_date: date | None = None
    proof_of_loss_due: date | None = None
    depreciation_deadline: date | None = None


class TransitionRequest(BaseModel):
    to_status: str = Field(pattern=_STATUS)
    # The repair working end (repairs ∪ claims merge, 2026-11-04):
    # where the item was sent (rides the move to in_repair) and
    # what the repair cost (rides the move to completed).
    # Warranty claims only — the service refuses them on
    # insurance claims.
    repair_sent_to: str | None = Field(default=None, max_length=300)
    repair_cost: Decimal | None = Field(default=None, ge=0)


class ProofOfLossSentRequest(BaseModel):
    sent_date: date | None = None


class ArchiveRequest(BaseModel):
    """Wave 3: archive / unarchive a claim."""

    archived: bool


class LinePackageRequest(BaseModel):
    """Wave 3: the per-line claim-package toggle."""

    include_in_package: bool


class LineCreate(BaseModel):
    target_kind: str = Field(pattern=_TARGET_KIND)
    target_id: uuid.UUID
    # Set lines only: the owner's answer to "include the addons?" —
    # asked by the UI, stored on the line, never re-derived.
    include_addons: bool = False
    value_basis: str = Field(default="purchase", pattern=_VALUE_BASIS)
    # Required when the basis is "entered" (always, for pieces);
    # ignored otherwise — computed bases price from current data.
    amount: Decimal | None = Field(default=None, ge=0)


class EvidenceReferenceCreate(BaseModel):
    item_kind: str = Field(pattern="^(tool|battery|piece)$")
    item_id: uuid.UUID
    attachment_key: str = Field(min_length=1, max_length=500)


class EvidenceUploadUrlRequest(BaseModel):
    kind: str = Field(pattern=_ATTACHMENT_KIND)
    filename: str = Field(min_length=1, max_length=200)
    content_type: str = Field(min_length=1, max_length=150)
    size_bytes: int | None = Field(default=None, gt=0)


class EvidenceAttachRequest(BaseModel):
    key: str = Field(min_length=1, max_length=500)
    filename: str = Field(default="", max_length=200)


class CommunicationCreate(BaseModel):
    channel: str = Field(default="phone", pattern=_CHANNEL)
    contact: str = Field(default="", max_length=300)
    summary: str = Field(default="", max_length=20000)
    # DATE ONLY (owner order, 2026-11-05 #9): the log takes the
    # day, never a time. A bare date is the normal shape now; a
    # full datetime from an older client still parses (datetime
    # is tried first) and is stored as sent — history keeps its
    # times, new entries are day-precise (the service normalizes
    # a date to that day's midnight).
    occurred_at: datetime | date | None = None


class CommunicationUpdate(BaseModel):
    channel: str | None = Field(default=None, pattern=_CHANNEL)
    contact: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=20000)
    occurred_at: datetime | date | None = None


# -- views ----------------------------------------------------------------------


class WarrantyAgentView(BaseModel):
    """A warranty claim's agent (agent scope, 2026-10-31): the
    one agent the claim runs through — a platform agent the owner
    recorded (kind "platform") or one of the owner's private
    agent records (kind "private"). has_access says whether the
    agent's seat is live: the pointer resolves to a platform user
    whose representation of the claim's dealer is VERIFIED. When
    it isn't, the agent cannot see the claim here and the owner
    keeps them updated himself."""

    kind: str
    agent_user_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID | None = None
    name: str = ""
    phone: str = ""
    email: str = ""
    account_number: str | None = None
    has_access: bool = False


class ChecklistItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    done: bool


class LineView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_id: uuid.UUID
    target_kind: str
    target_id: uuid.UUID
    set_id: uuid.UUID | None = None
    target_name: str
    set_name: str = ""
    # Piece lines: the piece's own part/model number + the parent
    # set's model number (Ryan 2026-10-25 — find it by either).
    target_part_number: str = ""
    set_model_number: str = ""
    include_addons: bool
    value_basis: str
    amount: Decimal | None = None
    # Wave 3: the per-line claim-package toggle.
    include_in_package: bool = True
    created_at: datetime


class EvidenceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_id: uuid.UUID
    source: str
    item_kind: str | None = None
    item_id: uuid.UUID | None = None
    attachment_key: str
    filename: str
    kind: str
    content_type: str = ""
    size_bytes: int = 0
    url: str | None = None
    available: bool = False
    created_at: datetime


class CommunicationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_id: uuid.UUID
    channel: str
    contact: str
    summary: str
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime
    # Authorship (2026-10-25): a warranty claim's log is written
    # by both sides. Pre-split rows read as the owner's.
    author_id: uuid.UUID | None = None
    author_role: str = "owner"
    author_name: str = ""


class ClaimView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_number: str
    # The claim kind (2026-10-25): warranty_repair |
    # insurance_disaster. Drives which header the page shows.
    kind: str = "insurance_disaster"
    insurer_name: str
    policy_number: str
    # Warranty claims: the dealer block + report facts.
    dealer_company_id: uuid.UUID | None = None
    dealer_name: str = ""
    # The filed-with mode (overhaul, 2026-11-06): agent | self |
    # corporate — who the claim's counterparty seat is.
    filed_with: str = "self"
    reported_at: datetime | None = None
    report_method: str = ""
    # The manufacturer's claim / case number (warranty claims —
    # they carry no insurance policy number) and the claim's
    # agent (2026-10-31): the one agent it runs through, or null
    # when it is the owner's alone. agent_options is the owner's
    # pick list for re-pointing (their agents on record for the
    # dealer); only the owner's seat receives it.
    manufacturer_case_number: str = ""
    # The repair working end on the claim itself (merge,
    # 2026-11-04): where the item was sent for repair, what the
    # repair cost, and when the work completed. Warranty claims
    # only; insurance claims leave them empty.
    repair_sent_to: str = ""
    repair_cost: Decimal | None = None
    repair_completed_at: datetime | None = None
    warranty_agent: WarrantyAgentView | None = None
    agent_options: list[WarrantyAgentView] = []
    # Who is looking ("owner" | "dealer" — the assigned agent's
    # seat keeps its standing name) and, for the agent seat, who
    # the customer is.
    viewer_role: str = "owner"
    owner_name: str = ""
    owner_email: str = ""
    # The claim's amounts are the OWNER's money, in the owner's
    # currency (wave-3 semantics): every surface labels them with
    # this — never the viewer's — and a cross-currency viewer gets
    # the approximate hint beside them. Matches the claim package,
    # which has always printed the owner's currency.
    owner_currency: str = ""
    # The agent block snapshotted at creation (Package C).
    agent_name: str = ""
    agent_phone: str = ""
    agent_email: str = ""
    incident_type: str
    incident_date: date | None = None
    description: str
    status: str
    police_report_number: str
    police_department: str
    police_report_date: date | None = None
    proof_of_loss_due: date | None = None
    proof_of_loss_sent_at: date | None = None
    depreciation_deadline: date | None = None
    filed_at: datetime | None = None
    closed_at: datetime | None = None
    # Wave 3: archive shelving (archived claims leave the default
    # lists + home stat; readable via the archived filter).
    archived: bool = False
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    lines: list[LineView] = []
    evidence: list[EvidenceView] = []
    communications: list[CommunicationView] = []
    checklist: list[ChecklistItemView] = []
    checklist_done: int = 0
    checklist_total: int = 0
    total_amount: Decimal = Decimal("0")
    allowed_transitions: list[str] = []


class ClaimDealerRef(BaseModel):
    id: uuid.UUID
    name: str


class ClaimSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_number: str
    kind: str = "insurance_disaster"
    dealer_name: str = ""
    filed_with: str = "self"
    # Warranty claims (2026-10-31): the agent the claim runs
    # through, by name ("" when none), and its manufacturer
    # claim / case number once assigned.
    warranty_agent_name: str = ""
    manufacturer_case_number: str = ""
    # The repair facts ride the summary (merge, 2026-11-04).
    repair_sent_to: str = ""
    repair_cost: Decimal | None = None
    insurer_name: str
    policy_number: str
    incident_type: str
    incident_date: date | None = None
    description: str
    status: str
    proof_of_loss_due: date | None = None
    proof_of_loss_sent_at: date | None = None
    depreciation_deadline: date | None = None
    filed_at: datetime | None = None
    # When the claim was reported to its dealer (warranty claims
    # are born with it) — the list's "Opened" date (claims
    # separation, 2026-11-05).
    reported_at: datetime | None = None
    closed_at: datetime | None = None
    # Wave 3: archive shelving (archived claims leave the default
    # lists + home stat; readable via the archived filter).
    archived: bool = False
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    line_count: int = 0
    # The first line's item, named the way claim items are named
    # everywhere (service._line_display_name — the home widget's
    # recent-claims rows read it, widget options Wave 2). Empty
    # when the claim carries no lines yet. Resolved from the
    # lines the summary already loads: no extra read, and the
    # list route's payload is the only place it is added.
    first_item_name: str = ""
    total_amount: Decimal = Decimal("0")
    # The repair working end (merge, 2026-11-04) — see service.
    repair_sent_to: str = ""
    repair_cost: Decimal | None = None
    # The owner's currency — total_amount is in it (see ClaimView).
    owner_currency: str = ""
    checklist_done: int = 0
    checklist_total: int = 0
    # Dealer intermingling (2026-10-25): the dealers this claim
    # touches through its items' dealer tags, resolved live by
    # the list route (service.dealers_for_claims). Empty when no
    # item on the claim carries a tag (or the items are gone).
    dealers: list[ClaimDealerRef] = []


class LinkedClaimRef(BaseModel):
    """The slim claim shape the dealer page and the item pages
    render: enough to recognize the claim and click through."""

    id: uuid.UUID
    claim_number: str
    kind: str = "insurance_disaster"
    dealer_name: str = ""
    filed_with: str = "self"
    status: str
    insurer_name: str
    incident_type: str
    incident_date: date | None = None
    total_amount: Decimal = Decimal("0")
    # The repair working end (merge, 2026-11-04) — see service.
    repair_sent_to: str = ""
    repair_cost: Decimal | None = None
    # The owner's currency — total_amount is in it (see ClaimView).
    owner_currency: str = ""
    created_at: datetime
    archived: bool = False
    items: list[str] = []


class ItemClaimsView(BaseModel):
    """One item's (or one dealer's) claims, split the way the
    pages show them: current (open) and history (closed/shelved)."""

    current: list[LinkedClaimRef] = []
    history: list[LinkedClaimRef] = []


class TargetAttachmentView(BaseModel):
    key: str
    filename: str
    kind: str
    content_type: str = ""
    size_bytes: int = 0
    url: str | None = None


class TargetPieceView(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    part_number: str = ""
    serial_number: str = ""
    status: str
    attachments: list[TargetAttachmentView] = []


class TargetView(BaseModel):
    kind: str
    id: uuid.UUID
    name: str
    brand: str = ""
    model: str = ""
    serial_number: str = ""
    quantity: int = 1
    purchase_price: Decimal | None = None
    replacement_cost: Decimal | None = None
    msrp: Decimal | None = None
    attachments: list[TargetAttachmentView] = []
    pieces: list[TargetPieceView] = []


class TargetsView(BaseModel):
    tools: list[TargetView] = []
    batteries: list[TargetView] = []


class PackageDriveView(BaseModel):
    filename: str
    drive_file_id: str = ""
    drive_link: str = ""
    emailed: bool = False
    via: str = "drive"


class PackageEmailView(BaseModel):
    filename: str
    emailed: bool = True
    via: str  # attachment | drive_link
    drive_file_id: str = ""
    drive_link: str = ""


class EvidenceUploadUrlView(BaseModel):
    upload_url: str
    key: str
    expires_in: int


class ClaimsStats(BaseModel):
    open_claims_count: int


# -- two kinds: warranty quick-create + the broken prompt (2026-10-25) --------


class WarrantyClaimCreate(BaseModel):
    """The broken-item flow's one-step warranty claim: what broke
    (an item, or one set piece), whether the addons ride along
    (set targets), the problem in the owner's words, and the
    answer to "have they been notified yet?" — the answer decides
    whether the system reports it itself.

    Agent (2026-10-31): with neither agent field set, the claim
    takes the owner's agent on record for the item's dealer.
    Naming one of the owner's recorded agents for that dealer
    (agent_user_id XOR private_agent_id) routes it there instead;
    no_agent=True files it as the owner's alone."""

    target_kind: str = Field(pattern=_TARGET_KIND)
    target_id: uuid.UUID
    include_addons: bool = False
    dealer_notified: bool
    problem: str = Field(default="", max_length=20000)
    agent_user_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID | None = None
    no_agent: bool = False
    # The filing ROUTE (overhaul, 2026-11-06): "agent" (through
    # the agent fields / the default agent on record), "self"
    # (the owner's alone — the no_agent outcome), or "corporate"
    # (straight with the dealer company; its verified reps become
    # the claim's counterparty seat). When sent it wins over the
    # legacy no_agent flag; when absent the old reading stands.
    filed_with: str | None = Field(
        default=None, pattern="^(agent|self|corporate)$"
    )


class ClaimAgentUpdate(BaseModel):
    """Re-point a warranty claim: the owner's agent of record for
    the claim's dealer to run it through — or both null for no
    agent (the claim becomes the owner's alone)."""

    agent_user_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID | None = None


class WarrantyFilingOptions(BaseModel):
    """The broken-item form's agent step for one target: the
    dealer the claim will name and the owner's agents on record
    for it (the pick list), with the default flagged by id."""

    dealer_company_id: uuid.UUID | None = None
    dealer_name: str = ""
    agents: list[WarrantyAgentView] = []
    default_agent_user_id: uuid.UUID | None = None
    default_private_agent_id: uuid.UUID | None = None


class WarrantyCreateResult(BaseModel):
    """The created claim plus the report outcome, so the caller
    can say honestly whether the dealer was reached."""

    claim: ClaimView
    reported: bool
    report_via: list[str] = []


class ReplaceItemRequest(BaseModel):
    """The broken prompt's Replace path. "same" = the exact same
    item (amount_spent is what the replacement cost — it becomes
    the new item's purchase price, with today as its purchase
    date); "different" = an upgrade: the old item retires and
    the user enters the new one through the normal add flow."""

    item_kind: str = Field(pattern="^(tool|battery)$")
    item_id: uuid.UUID
    mode: str = Field(pattern="^(same|different)$")
    amount_spent: Decimal | None = Field(default=None, ge=0)


class ReplaceItemResult(BaseModel):
    retired_id: uuid.UUID
    new_item: dict | None = None


class IncomingClaimSummary(ClaimSummary):
    """A warranty claim on the AGENT side's worklist (claims
    currently routed to the signed-in user as the assigned
    agent): the owner's summary plus the customer's name."""

    owner_name: str = ""
