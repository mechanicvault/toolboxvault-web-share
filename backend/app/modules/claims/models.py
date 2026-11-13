"""Claims module tables.

Owned exclusively by the claims module. Other modules read claim
data through service.py, never by importing these models. (Two
deliberate cross-module seams run the other way, both through
registries so no import cycle exists: this module REGISTERS a pin
provider into billing's entitlement engine and a delete guard into
inventory's service — see service.py's wiring note.)

Blueprint §15 + owner rules (2026-10-18/19):

- A claim is a header (insurer, incident, deadlines) + LINES. Each
  line targets an asset (tool | battery), a whole SET, or a single
  set PIECE — and SNAPSHOTS everything it priced at filing time
  (names, the include-addons choice for sets, the value basis and
  the amount), so a filed claim never drifts when the items later
  change, are renamed, or are re-priced.
- Pieces carry no price or replacement value of their own (the set
  owns the money), so a piece line's amount is owner-ENTERED.
- Evidence rows either REFERENCE an attachment that already lives
  on a targeted item (the file is never copied — the reference
  resolves live, with a filename snapshot so the row stays readable
  if the file is later removed) or hold a claim-specific UPLOAD
  (same storage shape as item attachments, keys namespaced
  {owner}/claims/{claim_id}/...).
- The communications log is the owner's record of every call and
  letter about the claim — plain rows, full CRUD.

Status flow (INSURANCE): draft -> filed -> in_review -> approved
-> paid -> closed, with denied branching off filed/in_review.
OPEN (for the billing lapse pin and the delete guards) means
filed / in_review / approved: the claim is live with the insurer
and its evidence must not grey out or be deleted mid-flight.
Drafts are the owner's scratch work — they pin nothing and block
nothing, and only drafts can be deleted.

TWO KINDS (owner model, confirmed 2026-10-25 — see
files/claims-two-types-model-2026-10-25.md): a claim is either a
WARRANTY / REPAIR claim (the everyday kind: a tool broke, the
dealer fixes or replaces it) or an INSURANCE DISASTER claim (the
rare kind: theft/loss/fire at scale, adjusters and police
reports). Every pre-split claim is an insurance claim — the
incident list (theft/loss/damage/fire/other) is loss events.

Warranty claims run their own status ladder on the same column:
not_reported -> reported -> in_repair -> completed -> closed
(the dealer has it / is fixing it between reported and
completed). They are born LIVE — created by the broken-item flow
in one step, never drafted — and they carry a DEALER (the item's
dealer tag, snapshotted as an id + name at creation) instead of
an insurer.

AGENT SCOPE (owner revision, 2026-10-31 — see
files/claims-agent-scope-revision-2026-10-31.md): a warranty
claim's second seat is ONE AGENT — the owner's dealer agent for
the claim (agent_user_id | private_agent_id, the same
exactly-one shape as a preferred-agent row) — or NO agent at
all. The dealer COMPANY is never a party: no company seat, no
other agents of the same company, no company-level lists. The
agent seat is live only when the agent record resolves to a
platform user whose representation of the claim's dealer is
VERIFIED (security finding H-1, folded in at agent level). An
agent with no account — or an unverified link — means the claim
has no second viewer and the owner runs it alone. When the
owner's agent on record for a dealer changes, claims seated
with the old agent are the owner's to move, keep, or delete
per claim (stage 1, 2026-11-04 — the auto-follow sweep is
retired).

CORPORATE EXCEPTION (owner order, 2026-11-05 #6 — claims
overhaul, 2026-11-06): a claim the owner files as
filed_with="corporate" names the dealer COMPANY as its
counterparty, deliberately bypassing the agent. Users holding
a VERIFIED representation of that company form its second seat
for THOSE claims only — the company seat never reaches agent-
or self-filed claims, and no agent pointer rides a corporate
claim. The agent-scope rule above stands untouched for the
agent route.

SEPARATION (owner order, 2026-11-04 — claims separation build,
2026-11-05): the two kinds are two completely separate
sections. The claims module serves WARRANTY claims only; the
disaster_claims module serves INSURANCE claims only. The table
stays shared (the billing pin, the inventory delete guards and
the item history feed all key off claim STATUS across kinds by
design — an open claim of either kind pins and guards its
items), but every section-facing read/write in service.py is
kind-scoped: a claim addressed through the wrong section's API
is a 404, indistinguishable from a stranger's claim.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
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

# Incident vocabulary (the app's claim types, kept small).
INCIDENT_TYPES = ("theft", "loss", "damage", "fire", "other")

# The two claim kinds (owner model, confirmed 2026-10-25).
KIND_WARRANTY = "warranty_repair"
KIND_INSURANCE = "insurance_disaster"
CLAIM_KINDS = (KIND_WARRANTY, KIND_INSURANCE)

# The visible number prefix per kind (claims separation,
# 2026-11-05): warranty claims are CL-<year>-<seq>; DISASTER
# claims mint DC-<year>-<seq> from their OWN per-owner sequence.
# Insurance claims filed before the separation keep the CL-
# numbers they already carry — claim_number is a stored string,
# so history never renumbers; only the mint differs.
NUMBER_PREFIXES = {KIND_WARRANTY: "CL", KIND_INSURANCE: "DC"}

STATUS_DRAFT = "draft"
STATUS_FILED = "filed"
STATUS_IN_REVIEW = "in_review"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_PAID = "paid"
STATUS_CLOSED = "closed"
STATUSES = (
    STATUS_DRAFT,
    STATUS_FILED,
    STATUS_IN_REVIEW,
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_PAID,
    STATUS_CLOSED,
)

# A claim is OPEN while the insurer is actively holding it: the
# lapse pin keeps its items active and the delete guards refuse to
# pull its evidence out from under it. Paid/denied/closed claims
# are history — they pin and block nothing.
OPEN_STATUSES = (STATUS_FILED, STATUS_IN_REVIEW, STATUS_APPROVED)

# The HOME stat's population (deep audit F1-23, 2026-10-23): every
# claim the owner still has in flight — drafts included. The Claims
# page lists drafts as live work in progress, so a home count that
# silently excluded them read 0 while the owner was mid-claim on
# two drafts. Terminal claims (denied / paid / closed) are history
# and never count. OPEN_STATUSES above keeps its narrower meaning
# for the lapse pin and delete guards, where a draft must NOT pin
# or block anything.
HOME_STATUSES = (STATUS_DRAFT, *OPEN_STATUSES)

# The legal moves. Anything not listed is refused with the current
# status named — the state machine is enforced in the service, not
# just drawn in the UI.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATUS_DRAFT: (STATUS_FILED,),
    STATUS_FILED: (STATUS_IN_REVIEW, STATUS_DENIED, STATUS_CLOSED),
    STATUS_IN_REVIEW: (STATUS_APPROVED, STATUS_DENIED, STATUS_CLOSED),
    STATUS_APPROVED: (STATUS_PAID, STATUS_CLOSED),
    STATUS_DENIED: (STATUS_CLOSED,),
    STATUS_PAID: (STATUS_CLOSED,),
    STATUS_CLOSED: (),
}

# -- warranty / repair ladder (2026-10-25; OVERHAULED 2026-11-06) -------
#
# Ryan's ladder, in his words (2026-11-05): Broken, not reported ·
# Broken, Reported · Waiting on agent · Waiting on replacement
# parts · Tool sent in for repairs · Agent has tool · Repaired ·
# Backordered. The keys keep their original spellings where the
# meaning is unchanged (not_reported / reported / in_repair /
# completed) — only the LABELS moved to Ryan's words; the four
# genuinely new states are new keys.
#
# The ladder is FREE-FORM (owner order, 2026-11-05): the owner AND
# the seated counterparty can each set ANY of the 8 statuses from
# any other — a repair's real life doesn't walk a fixed path, and
# the old restricted state machine (and the narrower agent move
# set) are retired on purpose.
#
# CLOSED IS NO LONGER A STATUS for warranty claims: closing is its
# own layer (the closed_at stamp, owner-only), orthogonal to the
# status — closing a claim moves it to Repair history with its
# status untouched. Insurance claims keep status-based closing.
# A warranty claim is OPEN — pinning its items and blocking their
# deletion — while it is in flight (any status but Repaired) and
# not closed.
STATUS_NOT_REPORTED = "not_reported"
STATUS_REPORTED = "reported"
STATUS_WAITING_ON_AGENT = "waiting_on_agent"
STATUS_WAITING_ON_PARTS = "waiting_on_parts"
STATUS_IN_REPAIR = "in_repair"
STATUS_AGENT_HAS_TOOL = "agent_has_tool"
STATUS_COMPLETED = "completed"
STATUS_BACKORDERED = "backordered"
WARRANTY_STATUSES = (
    STATUS_NOT_REPORTED,
    STATUS_REPORTED,
    STATUS_WAITING_ON_AGENT,
    STATUS_WAITING_ON_PARTS,
    STATUS_IN_REPAIR,
    STATUS_AGENT_HAS_TOOL,
    STATUS_COMPLETED,
    STATUS_BACKORDERED,
)


def _free_ladder(*, closer: bool) -> dict[str, tuple[str, ...]]:
    """Every warranty status may move to every other; the owner's
    map also carries the close action (to_status "closed" — the
    service turns it into the closed layer, never a status)."""
    moves: dict[str, tuple[str, ...]] = {}
    for status in WARRANTY_STATUSES:
        targets = tuple(s for s in WARRANTY_STATUSES if s != status)
        moves[status] = targets + ((STATUS_CLOSED,) if closer else ())
    moves[STATUS_CLOSED] = ()
    return moves


WARRANTY_TRANSITIONS: dict[str, tuple[str, ...]] = _free_ladder(closer=True)
# The moves the seated COUNTERPARTY (the verified agent, or the
# verified corporate reps on a corporate-filed claim) may make:
# the same free ladder, minus closing — closing is the owner's.
DEALER_WARRANTY_TRANSITIONS: dict[str, tuple[str, ...]] = _free_ladder(
    closer=False
)
# In flight for the pins, the delete guards, the home stat and
# the one-open-claim rule: every status but Repaired — and, at
# the query sites, only while the claim is not closed (closed_at
# IS NULL rides along there, because a claim closed from an open
# status keeps that status under the closed layer).
WARRANTY_OPEN_STATUSES = tuple(
    s for s in WARRANTY_STATUSES if s != STATUS_COMPLETED
)
# Every status in which a claim of EITHER kind is live: the pins
# and delete guards consult this union, never one kind's list.
ALL_OPEN_STATUSES = tuple(dict.fromkeys((*OPEN_STATUSES, *WARRANTY_OPEN_STATUSES)))
# Terminal per kind (the dealer/item pages' current-vs-history
# split): insurance ends at denied / paid / closed; a warranty
# claim ends at completed / closed.
INSURANCE_TERMINAL_STATUSES = (STATUS_DENIED, STATUS_PAID, STATUS_CLOSED)
WARRANTY_TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_CLOSED)


def transitions_for(claim: "Claim") -> dict[str, tuple[str, ...]]:
    """The state machine for THIS claim's kind."""
    return WARRANTY_TRANSITIONS if claim.kind == KIND_WARRANTY else TRANSITIONS


def is_terminal(claim: "Claim") -> bool:
    """History, for either kind: the process is over (archiving
    shelves a claim separately — see _is_current in service)."""
    terminal = (
        WARRANTY_TERMINAL_STATUSES
        if claim.kind == KIND_WARRANTY
        else INSURANCE_TERMINAL_STATUSES
    )
    return claim.status in terminal

# -- filed-with modes (claims overhaul, 2026-11-06) ----------------------
#
# Ryan's three filing routes (2026-11-05 #6): a warranty claim is
# filed WITH someone, and the mode names the counterparty seat:
#   agent     — runs through the owner's agent (the agent pointer
#               below); the verified agent is the second seat.
#   self      — the owner handles it alone; no second seat.
#   corporate — filed straight with the dealer COMPANY, bypassing
#               the agent: users holding a VERIFIED representation
#               of that company are the second seat, and they see
#               ONLY corporate-filed claims — never agent or self.
FILED_WITH_AGENT = "agent"
FILED_WITH_SELF = "self"
FILED_WITH_CORPORATE = "corporate"
FILED_WITH_MODES = (FILED_WITH_AGENT, FILED_WITH_SELF, FILED_WITH_CORPORATE)

# What a line can point at. "set" is its own kind (not "tool")
# because a set line is where the include-addons choice lives.
TARGET_KINDS = ("tool", "battery", "set", "piece")

# How a line's amount was derived. "entered" is the owner's own
# figure — the only basis a piece can carry, and always available
# for the others when the recorded values are missing.
VALUE_BASES = ("replacement", "msrp", "entered")

# Evidence kinds mirror the attachment kinds (storage allowlist).
EVIDENCE_KINDS = ("photo", "document", "receipt")

# Communications channels (the owner's log vocabulary).
COMM_CHANNELS = ("phone", "email", "mail", "portal", "in_person", "other")


class Claim(Base):
    """One insurance claim: header + deadlines. The items live in
    claim_lines; the paperwork in claim_evidence; the paper trail
    of conversations in claim_communications.

    claim_number is the owner-visible reference (CL-<year>-<seq>
    for warranty claims, DC-<year>-<seq> for disaster claims —
    sequential PER OWNER per year PER KIND since the claims
    separation, 2026-11-05), assigned at creation from
    claim_year/number_seq. Filed claims can never be deleted, so
    any number that reached an insurer is permanent; a deleted
    DRAFT's number (never filed, never shared) returns to the pool.
    """

    __tablename__ = "claims"
    __table_args__ = (
        # The number is assigned read-max-then-insert in the
        # service; this constraint is the race-proof backstop
        # (hardening 2026-10-19, migration 0024; kind added by the
        # claims separation, migration 0076): two creates in
        # flight at once can read the same max, but they can never
        # both COMMIT the same (owner, year, kind, seq) — the loser
        # gets an IntegrityError and the service retries with the
        # next number. Same pattern as borrowing's one-active-lend
        # index. The two kinds run SEPARATE sequences, so the kind
        # is part of the key.
        UniqueConstraint(
            "owner_id",
            "claim_year",
            "kind",
            "number_seq",
            name="uq_claims_owner_year_kind_seq",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    claim_number: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    claim_year: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    number_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The claim KIND (2026-10-25): warranty_repair | insurance_disaster.
    # Every row that predates the split is an insurance claim (the
    # migration defaults it so). The kind drives the status ladder,
    # the header facts (dealer vs insurer), and which surfaces show.
    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=KIND_INSURANCE,
        server_default=KIND_INSURANCE,
    )

    insurer_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    policy_number: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # Warranty claims: the DEALER the claim is with — the item's
    # dealer tag at creation, kept as an id (SET NULL if the
    # company is later deleted) plus a NAME SNAPSHOT so the record
    # still reads correctly after the company is gone. The dealer
    # is FACTUAL CONTEXT ONLY (2026-10-31): it names which dealer
    # the tool came from and grants nobody access — the claim's
    # agent pointer below is the only second seat.
    dealer_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="SET NULL"),
        index=True,
    )
    dealer_name: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    # The claim's AGENT (2026-10-31): the owner's dealer agent
    # this warranty claim runs through — a platform user
    # (agent_user_id) OR one of the owner's private agent records
    # (private_agent_id), the PreferredAgent exactly-one shape.
    # Both NULL = no agent: the claim is the owner's alone. The
    # default at filing is the owner's PREFERRED agent for the
    # dealer (stage 1, 2026-11-04: the one flagged connection
    # row); the owner can re-point a claim at any time, and a
    # re-point HOLDS — nothing moves a claim's seat silently.
    # Switching the preferred ASKS about each open claim seated
    # with the old agent (move / stay / delete, per claim); the
    # 2026-10-31 auto-follow sweep is retired.
    # SET NULL on either side: a deleted agent record (or a
    # deleted agent account) leaves the claim owner-only, never
    # dangling.
    agent_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    private_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("private_agents.id", ondelete="SET NULL"),
        index=True,
    )
    # The dealer agent's NAME, snapshotted when the private agent
    # record the claim was seated with is DELETED (stage 1,
    # 2026-11-04): the FK above SET NULLs the pointer, and this
    # keeps the claim attributed by name — the dealer_name
    # doctrine one seat down. Empty while the live pointer (or no
    # agent at all) tells the story.
    agent_name_snapshot: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    # The FILED-WITH mode (claims overhaul, 2026-11-06): which of
    # Ryan's three filing routes this warranty claim took — agent
    # / self / corporate (see FILED_WITH_MODES above). It decides
    # the counterparty seat: the mode rides WITH the seat (point
    # the claim at an agent and the mode follows to "agent";
    # clear the agent and it falls back to "self"; "corporate" is
    # chosen at filing and left only by re-pointing). Insurance
    # claims keep the column at its "self" default and never read
    # it — the disaster flow has no counterparty seat.
    filed_with: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=FILED_WITH_SELF,
        server_default=FILED_WITH_SELF,
    )
    # The BACKORDER clock (claims overhaul, 2026-11-06): when the
    # claim entered the Backordered status, and when the monthly
    # reminder last went out. Entering Backordered stamps the
    # first and clears the second (re-entering restarts the
    # clock); leaving the status stops future reminders without
    # erasing the history.
    backorder_entered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    backorder_last_reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # The manufacturer's claim / case number for a warranty claim
    # (the number the maker assigns when the claim is taken up).
    # Warranty claims have NO insurance policy — policy fields
    # belong to insurance claims only; this is their counterpart.
    manufacturer_case_number: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", server_default=""
    )
    # When the dealer was told, and how: report_method is
    # "system" (Toolbox Vault reported it — email and/or on-site
    # notice at creation) or "user" (the owner told the dealer
    # themselves). Empty until the claim is reported.
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report_method: Mapped[str] = mapped_column(
        String(20), nullable=False, default="", server_default=""
    )
    # The repair working end (repairs ∪ claims merge, 2026-11-04):
    # a warranty claim IS the repair — where the item was sent,
    # what the repair cost (an out-of-warranty paid repair is the
    # same claim with a cost on it), and when the work completed.
    # These absorb the retired maintenance repair_records fields
    # of the same names; migration 0074 converts the old records
    # into claims carrying them. Warranty claims only — insurance
    # claims never touch them.
    repair_sent_to: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    repair_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    repair_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # The agent contact block, SNAPSHOTTED from the owner's My
    # Insurance profile at creation (Package C, 2026-10-19) — or
    # typed on the claim itself. A snapshot, never a live link:
    # editing the profile later must not rewrite a filed claim's
    # record of who the agent was. Editable on the claim while it
    # runs (a typo fix), frozen with everything else at close.
    agent_name: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    agent_phone: Mapped[str] = mapped_column(
        String(60), nullable=False, default="", server_default=""
    )
    agent_email: Mapped[str] = mapped_column(
        String(320), nullable=False, default="", server_default=""
    )

    incident_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="other"
    )
    incident_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_DRAFT
    )

    # Police report block — the checklist treats it as required
    # for theft (the insurer will ask); stored plainly for the rest.
    police_report_number: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    police_department: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    police_report_date: Mapped[date | None] = mapped_column(Date)

    # Deadlines the insurer holds the owner to. proof_of_loss_due
    # pairs with proof_of_loss_sent_at (the checklist's "mark sent"
    # action); depreciation_deadline is the recoverable-depreciation
    # window on approved/paid claims. Both feed the jobs seam.
    proof_of_loss_due: Mapped[date | None] = mapped_column(Date)
    proof_of_loss_sent_at: Mapped[date | None] = mapped_column(Date)
    depreciation_deadline: Mapped[date | None] = mapped_column(Date)

    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Archive (wave 3, 2026-10-20): a shelved claim leaves the
    # default lists and the home stat but stays fully readable via
    # the archived filter — history is never deleted to declutter.
    # Archiving is journaled like every header change.
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClaimLine(Base):
    """One claimed item, SNAPSHOTTED at the moment it was added:
    names, set membership, the include-addons choice (set lines),
    the value basis and the computed amount. The snapshot never
    re-reads the item — later renames, re-pricing, detaches and
    even deletion of the item leave the filed claim exactly as it
    was made. target_id is deliberately NOT a foreign key (the
    ledger doctrine from borrowing/maintenance: the line outlives
    the item record; identity lives in the snapshot)."""

    __tablename__ = "claim_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    target_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # Piece lines (and set lines, = target_id): the parent set, so
    # the billing pin and the delete guards can find the asset that
    # actually carries the slot/standing — the set record.
    set_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)

    target_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    set_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Ryan 2026-10-25 (steering): a piece claim carries BOTH numbers —
    # the piece's own part/model number AND the parent set's model
    # number — because a dealer sometimes can only find the piece by
    # the set it came from. Snapshots, like every other line field.
    target_part_number: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    set_model_number: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    # Set lines only: the owner's answer to "include the addons?",
    # asked at filing and stored — never re-asked, never re-derived.
    include_addons: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    value_basis: Mapped[str] = mapped_column(
        String(20), nullable=False, default="replacement"
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # Claim package toggle (wave 3): whether this line appears in
    # the generated claim package PDF. Default IN — the owner
    # excludes a line deliberately, never by accident.
    include_in_package: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClaimEvidence(Base):
    """One piece of evidence on a claim.

    source="reference": points at an attachment already stored on
    one of the owner's items (item_kind/item_id/attachment_key);
    filename + kind are snapshotted so the row stays readable if
    the file is later removed from the item — the view resolves
    the live URL when the file is still there and says so when it
    isn't. The file itself is never copied.

    source="upload": a file uploaded for THIS claim; `attachment`
    holds the stored dict (key/filename/kind/content_type/
    size_bytes/uploaded_at) in exactly the item-attachment shape,
    keys namespaced {owner}/claims/{claim_id}/...
    """

    __tablename__ = "claim_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source: Mapped[str] = mapped_column(String(10), nullable=False, default="reference")
    # Reference rows only.
    item_kind: Mapped[str | None] = mapped_column(String(10))
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attachment_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Snapshot for both sources (for uploads it mirrors the dict).
    filename: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="document")
    # Upload rows only: the full stored attachment dict.
    attachment: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClaimCommunication(Base):
    """One entry in the claim's communications log: a call, an
    email, a letter — when it happened, through what channel, with
    whom, and what was said/decided. Plain owner CRUD; the log is
    the owner's memory at adjustment time."""

    __tablename__ = "claim_communications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="phone")
    contact: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Authorship (2026-10-25): a warranty claim's log is a
    # TWO-PARTY record — the owner and the dealer side both write
    # in it. author_role is "owner" | "dealer"; author_name is the
    # writer's display name, snapshotted so the entry still reads
    # right if the account later changes. Rows that predate the
    # split (and every insurance-claim row) are the owner's:
    # author_id NULL, author_role "".
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    author_role: Mapped[str] = mapped_column(
        String(10), nullable=False, default="", server_default=""
    )
    author_name: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
