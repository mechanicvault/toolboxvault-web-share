"""Claims service: insurance claims over the owner's vault.

SERVICE INTERFACE (stable; bump manifest version on change):
  - create_claim / update_claim / delete_claim (drafts only) /
    transition / mark_proof_of_loss_sent
  - add_line / remove_line — targets (asset | set | piece) priced
    and SNAPSHOTTED at add time; the stored row never re-reads the
    item afterwards
  - add_evidence_reference / issue_evidence_upload_url /
    attach_evidence_upload / remove_evidence
  - add_communication / update_communication / delete_communication
  - claim_view / list_claims / checklist — the read picture: lines,
    evidence (references resolved live), comms log, the computed
    todo checklist, allowed transitions, and (for damage claims)
    the targeted items' repair records via maintenance's seam
  - list_targets — the wizard's picker: the owner's assets with
    the values and attachments a claim line can draw on
  - create_warranty_claim — the broken-item flow's one-step
    warranty claim (kind=warranty_repair): auto-created for an
    item or a single set piece, routed to the owner's dealer
    AGENT for the item's dealer (the agent on record by default;
    a different recorded agent, or no agent, at the owner's
    pick), auto-reported to that agent when a channel reaches
    them (owner revision 2026-10-31)
  - claim_party_user_ids / list_incoming_claims /
    get_claim_for_viewer / set_claim_agent — the AGENT side of a
    warranty claim: the ONE agent the claim is routed to can see
    it, drive its repair statuses, and share its log + evidence
    — only while their link to the claim's dealer is VERIFIED.
    The dealer company is never a party; with no agent (or no
    verified link) the claim is the owner's alone
  - claims_seated_with_agent — the agent-record reads the
    dealers roster uses (stage 1, 2026-11-04). NOTHING here
    re-points claims on its own: the 2026-10-31 follow sweep
    is retired — a claim's seat changes only by the owner's
    per-claim choice
  - replace_item — the broken prompt's replace path: a NEW item
    carrying the old one's data (exact-same: everything but price
    and purchase date), the old one retired to the "replaced"
    standing — out of lists, search and the plan's active set,
    still readable by reports and history
  - stats(db, owner_id) -> {"open_claims_count": int}
  - pinned_asset_ids(db, owner_id) — billing's lapse-pin provider
  - delete_guard(db, owner_id, kind, item_id) — inventory's guard
  - run_deadline_notifications(db, today=None) -> int (jobs seam)
  - export_rows(db, owner_id) — the data export's claims.json

CROSS-MODULE WIRING (import time, one direction only): this
module registers pinned_asset_ids into billing's pin-provider
registry (the seam the A1 engine left in _active_asset_ids:
"items pinned by an active insurance claim stay active regardless
of the limit") and delete_guard into inventory's delete-guard
registry. Billing and inventory never import claims — the
registries are the whole connection, so removing this module
removes the pins and guards with it, and neither engine changes
behavior for anyone without claims.

OPEN means filed / in_review / approved for an INSURANCE claim:
drafts pin nothing and block nothing; paid / denied / closed
claims are history. A WARRANTY claim is open from birth until it
completes (not_reported / reported / in_repair) — the pins and
guards consult models.ALL_OPEN_STATUSES, the union of both kinds.
"""

import uuid
import zlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.storage import ALLOWED_CONTENT_TYPES, StorageError, storage
from app.modules.billing import entitlements
from app.modules.claims import models
from app.modules.core import inbox, journal
from app.modules.core import insurance as core_insurance
from app.modules.core import money as core_money
from app.modules.core import models as core_models
from app.modules.inventory import attachments as inventory_attachments
from app.modules.inventory import history as inventory_history
from app.modules.inventory import models as inventory_models
from app.modules.inventory import service as inventory_service

OPEN_STATUSES = models.OPEN_STATUSES

# Statuses in which the insurer is still deciding — the proof of
# loss conversation happens here.
_PRE_DECISION_STATUSES = (models.STATUS_FILED, models.STATUS_IN_REVIEW)

# A deadline earns its notification this many days out (and when
# overdue) — one notification per claim + deadline, ever.
DEADLINE_WARNING_DAYS = 7


class ClaimsError(ValueError):
    """Caller turns this into a 4xx."""


class ClaimsNotFound(ClaimsError):
    """The claim/line/entry named does not exist (or is not the
    caller's — deliberately indistinguishable)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _comm_moment(value: datetime | date | None) -> datetime | None:
    """A communications-log moment (date-only overhaul,
    2026-11-06): the log takes a DATE now — a plain date lands
    as that day's midnight UTC, so the stored stamp stays a
    datetime (history keeps its times; only the entry surface
    dropped them) while every new entry is day-precise. A real
    datetime (older clients) passes through untouched."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


_CENTS = Decimal("0.01")


def _money(value) -> Decimal:
    """Exact 2dp money, the inventory convention (SQLite SUM dust
    never reaches a snapshot)."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(_CENTS)


# -- claim header ------------------------------------------------------------


def _claim_or_404(
    db: Session,
    owner_id: uuid.UUID,
    claim_id: uuid.UUID,
    kind: str | None = None,
) -> models.Claim:
    """Resolve one of the owner's claims. `kind` is the SECTION
    scope (claims separation, 2026-11-05): a claim of the other
    kind addressed through this section is the same not-found as
    a stranger's claim — the two sections never leak each other's
    records. Internal cross-section callers (deletion cascades,
    the agent-record seams) pass no kind."""
    claim = db.get(models.Claim, claim_id)
    if claim is None or claim.owner_id != owner_id:
        raise ClaimsNotFound("That claim doesn't exist.")
    if kind is not None and claim.kind != kind:
        raise ClaimsNotFound("That claim doesn't exist.")
    return claim


def _next_number(
    db: Session, owner_id: uuid.UUID, kind: str
) -> tuple[str, int, int]:
    """The owner's next claim number for this year IN THIS KIND:
    CL-<year>-<seq> for warranty, DC-<year>-<seq> for disaster
    (models.NUMBER_PREFIXES) — each kind runs its own per-owner
    sequence since the separation (2026-11-05), so a disaster
    claim's number never advances the warranty sequence and vice
    versa. Filed claims can't be deleted, so a number that
    reached an insurer is never reused; a deleted draft's number
    was never shared and returns to its kind's pool."""
    year = date.today().year
    current_max = db.scalar(
        select(func.max(models.Claim.number_seq)).where(
            models.Claim.owner_id == owner_id,
            models.Claim.claim_year == year,
            models.Claim.kind == kind,
        )
    )
    seq = (current_max or 0) + 1
    prefix = models.NUMBER_PREFIXES[kind]
    return f"{prefix}-{year}-{seq:03d}", year, seq


def create_claim(
    db: Session, owner: core_models.User, **fields
) -> models.Claim:
    """Open a new DRAFT claim with the next number. Fields are the
    header facts (insurer, incident, deadlines); everything is
    optional at birth — the wizard fills the claim in step by step
    and the checklist tracks what's still missing.

    MY INSURANCE PRE-FILL + AGENT SNAPSHOT (Package C): when the
    create leaves insurer_name / policy_number blank, they come
    from the owner's My Insurance profile (core.insurance) — the
    claim form opens pre-filled and stays editable per claim. The
    agent block (name/phone/email) is SNAPSHOTTED the same way:
    values sent with the create win, blanks fall back to the
    profile, and what lands on the claim is a copy — editing the
    profile later never rewrites a filed claim.

    Number assignment races safely (hardening 2026-10-19): the
    (owner, year, seq) unique constraint (migration 0024) means two
    creates in flight can never both commit the same number — the
    loser retries here with the next one instead of surfacing a
    500, so a double-submitted create yields two claims with two
    distinct numbers, never a duplicate and never an error."""
    profile = core_insurance.get_profile(db, owner.id)

    def _field(name: str, profile_value: str = "") -> str:
        value = (fields.get(name) or "").strip()
        return value or profile_value

    insurer_name = _field(
        "insurer_name", profile.insurer_company if profile else ""
    )
    policy_number = _field(
        "policy_number", profile.policy_number if profile else ""
    )
    agent_name = _field("agent_name", profile.agent_name if profile else "")
    agent_phone = _field(
        "agent_phone", profile.agent_phone if profile else ""
    )
    agent_email = _field(
        "agent_email", profile.agent_email if profile else ""
    )
    for _attempt in range(10):
        number, year, seq = _next_number(db, owner.id, models.KIND_INSURANCE)
        claim = models.Claim(
            owner_id=owner.id,
            claim_number=number,
            claim_year=year,
            number_seq=seq,
            kind=models.KIND_INSURANCE,
            insurer_name=insurer_name,
            policy_number=policy_number,
            agent_name=agent_name,
            agent_phone=agent_phone,
            agent_email=agent_email,
            incident_type=fields.get("incident_type") or "other",
            incident_date=fields.get("incident_date"),
            description=fields.get("description") or "",
            police_report_number=(fields.get("police_report_number") or "").strip(),
            police_department=(fields.get("police_department") or "").strip(),
            police_report_date=fields.get("police_report_date"),
            proof_of_loss_due=fields.get("proof_of_loss_due"),
            depreciation_deadline=fields.get("depreciation_deadline"),
        )
        db.add(claim)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(claim)
        return claim
    raise ClaimsError(
        "Couldn't assign a claim number after several tries — please retry."
    )


# Facts that describe the incident itself — they define the claim,
# so they freeze when it leaves draft.
_INCIDENT_FIELDS = ("incident_type", "incident_date")
# Facts that can be corrected while the claim runs its course
# (insurer details, paperwork, deadlines) — until it closes.
# INSURANCE claims only: a warranty claim has no insurer and no
# policy (2026-10-31), so none of these can land on one.
_FOLLOWUP_FIELDS = (
    "insurer_name",
    "policy_number",
    # The claim's own agent snapshot (Package C) — editable while
    # the claim runs; editing it never touches the profile.
    "agent_name",
    "agent_phone",
    "agent_email",
    "description",
    "police_report_number",
    "police_department",
    "police_report_date",
    "proof_of_loss_due",
    "depreciation_deadline",
)
# A WARRANTY claim's correctable facts: what happened, and the
# manufacturer's claim / case number once the maker assigns one.
_WARRANTY_FOLLOWUP_FIELDS = ("description", "manufacturer_case_number")


def update_claim(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    kind: str | None = None,
    **changes,
) -> models.Claim:
    claim = _claim_or_404(db, owner.id, claim_id, kind=kind)
    if _is_closed(claim):
        raise ClaimsError(
            f"Claim {claim.claim_number} is closed — its record is final."
        )
    followups = (
        _WARRANTY_FOLLOWUP_FIELDS
        if claim.kind == models.KIND_WARRANTY
        else _FOLLOWUP_FIELDS
    )
    for key, value in changes.items():
        if key in _INCIDENT_FIELDS and claim.status != models.STATUS_DRAFT:
            if getattr(claim, key) != value:
                raise ClaimsError(
                    "The incident details are part of the filed claim — "
                    "they can't change after filing."
                )
            continue
        if key not in _INCIDENT_FIELDS and key not in followups:
            continue  # unknown — or wrong-kind — keys never land
        if isinstance(value, str):
            value = value.strip()
        setattr(claim, key, value)
    db.commit()
    db.refresh(claim)
    return claim


def delete_claim(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    kind: str | None = None,
) -> bool:
    """Delete a DRAFT claim and everything attached to it. Filed
    claims are the insurer-facing record — those close, they don't
    delete. Uploaded evidence files are cleaned up best-effort."""
    claim = db.get(models.Claim, claim_id)
    if claim is None or claim.owner_id != owner.id:
        return False
    if kind is not None and claim.kind != kind:
        return False
    if claim.status != models.STATUS_DRAFT:
        raise ClaimsError(
            "Only a draft claim can be deleted — a filed claim is "
            "closed instead, so the record stays complete."
        )
    for row in db.scalars(
        select(models.ClaimEvidence).where(models.ClaimEvidence.claim_id == claim.id)
    ):
        if row.source == "upload" and row.attachment:
            key = row.attachment.get("key")
            if key:
                # Tombstoned, not destroyed (audit trail): only
                # drafts can be deleted, and draft deletes restore.
                journal.retire_keys(
                    db, owner.id, [key],
                    entity_type="claim_evidence", entity_id=row.id,
                )
        db.delete(row)
    for model in (models.ClaimLine, models.ClaimCommunication):
        for row in db.scalars(select(model).where(model.claim_id == claim.id)):
            db.delete(row)
    db.delete(claim)
    db.commit()
    return True


# Plain words for the warranty ladder, for notification copy —
# Ryan's status words (2026-11-05), lower-cased for mid-sentence.
_WARRANTY_STATUS_WORDS = {
    models.STATUS_NOT_REPORTED: "broken, not reported",
    models.STATUS_REPORTED: "broken, reported",
    models.STATUS_WAITING_ON_AGENT: "waiting on agent",
    models.STATUS_WAITING_ON_PARTS: "waiting on replacement parts",
    models.STATUS_IN_REPAIR: "tool sent in for repairs",
    models.STATUS_AGENT_HAS_TOOL: "agent has tool",
    models.STATUS_COMPLETED: "repaired",
    models.STATUS_BACKORDERED: "backordered",
    models.STATUS_CLOSED: "closed",
}


def _is_closed(claim: models.Claim) -> bool:
    """Closed, per kind (claims overhaul, 2026-11-06): for a
    WARRANTY claim closing is its own layer — the claim is closed
    when closed_at is stamped, whatever its status says (a claim
    closed from an open status keeps that status). Insurance
    claims keep status-based closing."""
    if claim.kind == models.KIND_WARRANTY:
        return claim.closed_at is not None
    return claim.status == models.STATUS_CLOSED


def _sync_warranty_standing(
    db: Session, claim: models.Claim, to_status: str
) -> None:
    """The merged repair pipeline's standing writer (repairs ∪
    claims merge, 2026-11-04): a warranty claim IS the item's
    repair, so the item's standing follows the claim —

      claim created / reported  -> the item reads BROKEN (set at
                                   creation; reported changes
                                   nothing — it is still here,
                                   still broken)
      -> in_repair              -> the item reads IN REPAIR
                                   ("sent out") when it was broken
      -> completed              -> the item returns to service
                                   when it was broken / in repair

    The overhauled ladder (2026-11-06) extends the same mapping
    over Ryan's new statuses by where the tool physically is:
      -> agent_has_tool         -> away with the agent: IN REPAIR,
                                   like sent in (the Out of
                                   service board reads it the same)
      -> waiting / backordered /
         not reported / reported -> the tool is HERE and broken:
                                   an item that was out comes back
                                   to BROKEN, one that never left
                                   stays BROKEN.

    Closing an OPEN claim changes nothing: the claim was
    abandoned, the item is still broken. Lost/stolen/sold/
    replaced items are never touched — their standing outranks
    the repair. Pieces carry repair_state only, the same trio.
    Insurance claims never come through here."""
    if claim.kind != models.KIND_WARRANTY:
        return
    away = (models.STATUS_IN_REPAIR, models.STATUS_AGENT_HAS_TOOL)
    home_broken = (
        models.STATUS_NOT_REPORTED,
        models.STATUS_REPORTED,
        models.STATUS_WAITING_ON_AGENT,
        models.STATUS_WAITING_ON_PARTS,
        models.STATUS_BACKORDERED,
    )
    for line in _lines(db, claim.id):
        record = _resolve_target(
            db, claim.owner_id, line.target_kind, line.target_id
        )
        if record is None:
            continue
        if line.target_kind == "piece":
            if to_status in away:
                if record.repair_state == inventory_models.STANDING_BROKEN:
                    record.repair_state = inventory_models.STANDING_IN_REPAIR
            elif to_status == models.STATUS_COMPLETED:
                if record.repair_state in (
                    inventory_models.STANDING_BROKEN,
                    inventory_models.STANDING_IN_REPAIR,
                ):
                    record.repair_state = inventory_models.STANDING_IN_SERVICE
                    # Back in service clears the problem text —
                    # the same end state apply_standing produces
                    # for whole items.
                    record.repair_problem = ""
            elif to_status in home_broken:
                if record.repair_state == inventory_models.STANDING_IN_REPAIR:
                    record.repair_state = inventory_models.STANDING_BROKEN
            continue
        standing = getattr(record, "standing", None)
        if to_status in away:
            if standing == inventory_models.STANDING_BROKEN:
                inventory_service.apply_standing(
                    record, inventory_models.STANDING_IN_REPAIR
                )
        elif to_status == models.STATUS_COMPLETED:
            if standing in (
                inventory_models.STANDING_BROKEN,
                inventory_models.STANDING_IN_REPAIR,
            ):
                inventory_service.apply_standing(
                    record, inventory_models.STANDING_IN_SERVICE
                )
        elif to_status in home_broken:
            if standing == inventory_models.STANDING_IN_REPAIR:
                inventory_service.apply_standing(
                    record, inventory_models.STANDING_BROKEN
                )


def transition(
    db: Session,
    actor: core_models.User,
    claim_id: uuid.UUID,
    to_status: str,
    *,
    repair_sent_to: str | None = None,
    repair_cost: Decimal | None = None,
    kind: str | None = None,
) -> models.Claim:
    """Move the claim along ITS KIND's flow. The state machines
    live in models (TRANSITIONS for insurance, WARRANTY_TRANSITIONS
    for warranty); an illegal move is refused with the legal ones
    named, so the caller never has to guess.

    The actor may be the claim's owner or — for a warranty claim —
    its seated counterparty (the verified agent, or the verified
    corporate reps on a corporate-filed claim). Since the claims
    overhaul (2026-11-06) the warranty ladder is FREE-FORM: both
    seats can set ANY of the 8 statuses — the one move reserved
    to the owner is CLOSING, which on a warranty claim is not a
    status at all but the closed layer (closed_at): the status
    stays exactly where it was and the claim moves to Repair
    history. A closed warranty claim is final — no status moves
    until (as ever) there is nothing to reopen it with. A
    warranty move notifies the other side in the same breath.

    The repair working end (merge, 2026-11-04): moving a WARRANTY
    claim to in_repair may carry where the item was sent
    (repair_sent_to), and moving it to completed may carry what
    the repair cost (repair_cost) — a paid, out-of-warranty
    repair is the same claim with a cost on it. Completing stamps
    repair_completed_at, and the target item's standing follows
    the claim (see _sync_warranty_standing). Repair facts on an
    insurance claim are refused — they belong to warranty claims.

    Entering BACKORDERED stamps the backorder clock (entered-at
    now, last-reminded cleared) — the monthly reminder job runs
    off those two stamps; leaving the status simply stops the
    job from picking the claim up.
    """
    claim, role = _claim_for_actor(db, actor, claim_id, kind=kind)
    if (repair_sent_to is not None or repair_cost is not None) and (
        claim.kind != models.KIND_WARRANTY
    ):
        raise ClaimsError(
            "Repair details belong to warranty claims — an insurance "
            "claim has no repair to send out or pay for."
        )
    if claim.kind == models.KIND_WARRANTY and _is_closed(claim):
        raise ClaimsError(
            f"Claim {claim.claim_number} is closed — its record is final."
        )
    if role == "dealer":
        allowed = models.DEALER_WARRANTY_TRANSITIONS.get(claim.status, ())
    else:
        allowed = models.transitions_for(claim)[claim.status]
    if to_status not in allowed:
        if (
            role == "dealer"
            and claim.kind == models.KIND_WARRANTY
            and to_status == models.STATUS_CLOSED
        ):
            # Closing is the owner's move alone (overhaul,
            # 2026-11-06): the counterparty's free ladder offers
            # every status EXCEPT this one. The refusal names the
            # owner — the claim is not final and must never be
            # described as final (deep audit round 2, E-03).
            raise ClaimsError(
                f"A {claim.status} claim can't move to {to_status}. "
                "Closing a claim is the owner's move — only the "
                "owner can take it from this point."
            )
        if role == "dealer" and not allowed:
            # The dealer's move set being empty does NOT make the
            # claim final (deep audit round 2, E-03): from
            # "completed" the OWNER can still close it, and from
            # "not reported yet" the owner still drives it. Saying
            # "it is final" here was untrue — phrase the refusal
            # from the dealer's seat instead. A claim the owner
            # also cannot move (closed) keeps the honest wording.
            owner_allowed = models.transitions_for(claim).get(claim.status, ())
            if owner_allowed:
                raise ClaimsError(
                    f"A {claim.status} claim can't move to {to_status}. "
                    "You can't move this claim from here — only the "
                    "owner can take it from this point (they can move "
                    f"it to: {', '.join(owner_allowed)})."
                )
        options = ", ".join(allowed) if allowed else "nothing — it is final"
        raise ClaimsError(
            f"A {claim.status} claim can't move to {to_status}. "
            f"From here it can move to: {options}."
        )
    if claim.kind == models.KIND_WARRANTY and to_status == models.STATUS_CLOSED:
        # Closing a warranty claim (overhaul, 2026-11-06): the
        # closed LAYER, not a status — the ladder position stays
        # exactly where it was, closed_at stamps, and the claim
        # moves to Repair history. Only the owner can be here:
        # the counterparty's move set never offers "closed".
        # Standing does not change (closing an open claim never
        # fixed or freed the item).
        claim.closed_at = _now()
        db.commit()
        db.refresh(claim)
        lines = _lines(db, claim.id)
        item_name = _line_display_name(lines[0]) if lines else "an item"
        actor_name = _actor_display_name(db, actor)
        _notify_warranty_activity(
            db,
            claim,
            actor.id,
            title=f"Warranty claim {claim.claim_number}",
            body=(
                f"{actor_name} closed the claim for {item_name}."
            ),
        )
        return claim
    claim.status = to_status
    if to_status == models.STATUS_FILED and claim.filed_at is None:
        claim.filed_at = _now()
    if to_status == models.STATUS_REPORTED and claim.reported_at is None:
        claim.reported_at = _now()
        if not claim.report_method:
            claim.report_method = "user"
    if to_status == models.STATUS_CLOSED:
        claim.closed_at = _now()
    if claim.kind == models.KIND_WARRANTY:
        # The repair working end rides the ladder moves: the
        # send captures its destination, the completion captures
        # its cost and stamps when the work finished — closing
        # the claim later keeps both (the old repair record's
        # "closing keeps the cost" semantics, on the claim now).
        if to_status == models.STATUS_IN_REPAIR and repair_sent_to is not None:
            claim.repair_sent_to = repair_sent_to.strip()
        if to_status == models.STATUS_COMPLETED:
            if repair_cost is not None:
                claim.repair_cost = _money(repair_cost)
            if claim.repair_completed_at is None:
                claim.repair_completed_at = _now()
        if to_status == models.STATUS_BACKORDERED:
            # The backorder clock starts (or restarts): the first
            # reminder falls due one month from here.
            claim.backorder_entered_at = _now()
            claim.backorder_last_reminded_at = None
        _sync_warranty_standing(db, claim, to_status)
    db.commit()
    db.refresh(claim)
    if claim.kind == models.KIND_WARRANTY:
        lines = _lines(db, claim.id)
        item_name = _line_display_name(lines[0]) if lines else "an item"
        actor_name = _actor_display_name(db, actor)
        _notify_warranty_activity(
            db,
            claim,
            actor.id,
            title=f"Warranty claim {claim.claim_number}",
            body=(
                f"{actor_name} moved the claim for {item_name} to "
                f"{_WARRANTY_STATUS_WORDS.get(to_status, to_status)}."
            ),
        )
    return claim


def mark_proof_of_loss_sent(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    sent_date: date | None = None,
    kind: str | None = None,
) -> models.Claim:
    """The checklist action: the proof of loss went to the insurer
    on this date. Only meaningful once the claim is with the
    insurer (filed / in review / approved)."""
    claim = _claim_or_404(db, owner.id, claim_id, kind=kind)
    if claim.status not in OPEN_STATUSES:
        if claim.status == models.STATUS_DRAFT:
            raise ClaimsError(
                "Proof of loss is sent after the claim is filed — "
                "this claim is still a draft."
            )
        raise ClaimsError(
            f"This claim is {claim.status} — its proof of loss is settled history."
        )
    claim.proof_of_loss_sent_at = sent_date or date.today()
    db.commit()
    db.refresh(claim)
    return claim


# -- wave 3 extras: archive, duplicate, package toggles -------------------------


def set_archived(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    archived: bool,
    kind: str | None = None,
) -> models.Claim:
    """Shelve / unshelve a claim. Archived claims leave the
    default lists and the home stat but stay fully readable —
    archiving is decluttering, never deletion. Journaled like
    every other header change."""
    claim = _claim_or_404(db, owner.id, claim_id, kind=kind)
    claim.archived = bool(archived)
    claim.archived_at = _now() if archived else None
    db.commit()
    db.refresh(claim)
    return claim


def duplicate_claim(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    kind: str | None = None,
) -> models.Claim:
    """Copy a claim into a NEW DRAFT with a fresh number: the
    incident fields + agent/insurer block + the targeted lines
    (snapshots carried verbatim — the items may have changed or
    gone since, and the new claim says what the old one said).
    Evidence and the comms log do NOT copy: they belong to the
    original claim's history. Deadlines do not copy either —
    they were the old incident's timeline, and the wizard asks
    again."""
    source = _claim_or_404(db, owner.id, claim_id, kind=kind)
    if source.kind == models.KIND_WARRANTY:
        raise ClaimsError(
            "Duplicate is for insurance claims — a warranty claim "
            "starts from the broken item itself, so the new claim "
            "carries the item's current data."
        )
    clone = create_claim(
        db,
        owner,
        insurer_name=source.insurer_name,
        policy_number=source.policy_number,
        agent_name=source.agent_name,
        agent_phone=source.agent_phone,
        agent_email=source.agent_email,
        incident_type=source.incident_type,
        incident_date=source.incident_date,
        description=source.description,
        police_report_number=source.police_report_number,
        police_department=source.police_department,
        police_report_date=source.police_report_date,
    )
    for line in _lines(db, source.id):
        db.add(
            models.ClaimLine(
                owner_id=owner.id,
                claim_id=clone.id,
                target_kind=line.target_kind,
                target_id=line.target_id,
                set_id=line.set_id,
                target_name=line.target_name,
                set_name=line.set_name,
                target_part_number=line.target_part_number,
                set_model_number=line.set_model_number,
                include_addons=line.include_addons,
                value_basis=line.value_basis,
                amount=line.amount,
                include_in_package=bool(line.include_in_package),
            )
        )
    db.commit()
    db.refresh(clone)
    return clone


def set_line_package(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    line_id: uuid.UUID,
    include: bool,
    kind: str | None = None,
) -> models.ClaimLine:
    """The per-line package toggle: this line appears in (or
    stays out of) the generated claim package PDF. A closed
    claim's record is final, toggles included."""
    claim = _claim_or_404(db, owner.id, claim_id, kind=kind)
    if claim.status == models.STATUS_CLOSED:
        raise ClaimsError(
            f"Claim {claim.claim_number} is closed — its record is final."
        )
    row = db.get(models.ClaimLine, line_id)
    if row is None or row.claim_id != claim.id:
        raise ClaimsNotFound("That claim line doesn't exist.")
    row.include_in_package = bool(include)
    db.commit()
    db.refresh(row)
    return row


# -- lines ---------------------------------------------------------------------


def _resolve_target(
    db: Session, owner_id: uuid.UUID, target_kind: str, target_id: uuid.UUID
):
    """The owner's inventory record for a line target, or None.
    Sets resolve through the tool getter (a set IS a tool record);
    the kind check happens in add_line."""
    if target_kind in ("tool", "set"):
        return inventory_service.get_tool(db, owner_id, target_id)
    if target_kind == "battery":
        return inventory_service.get_battery(db, owner_id, target_id)
    if target_kind == "piece":
        return inventory_service.get_set_piece(db, owner_id, target_id)
    raise ClaimsError("Claim lines target a tool, a battery, a set, or a set piece.")


def _line_amount(
    db: Session,
    owner: core_models.User,
    *,
    target_kind: str,
    record,
    include_addons: bool,
    value_basis: str,
    entered_amount,
) -> Decimal:
    """Price a line from CURRENT data (the result is snapshotted —
    this function runs exactly once, when the line is added).
    Money is per-unit x quantity for assets; a set prices through
    inventory's shared membership service so addons follow the
    stored choice; a piece has no value of its own, so its amount
    is always the owner's entered figure."""
    if target_kind == "piece":
        if value_basis != "entered":
            raise ClaimsError(
                "A set piece has no replacement value of its own — "
                "the price lives on the set. Enter the amount for this piece."
            )
        if entered_amount is None:
            raise ClaimsError("Enter the amount for this piece.")
        return _money(entered_amount)
    if value_basis == "entered":
        if entered_amount is None:
            raise ClaimsError("Enter the amount for this line.")
        return _money(entered_amount)
    if value_basis == "purchase":
        # Claim money is PURCHASE COST (owner ruling, 2026-11-06):
        # what the owner paid — per-unit x quantity for an asset;
        # for a set, the shared membership service's price_total,
        # which is exactly the purchase-cost sum over the included
        # members (the set's own purchase price, addon pieces'
        # recorded prices, attached tools' purchase prices).
        if target_kind == "set":
            members = inventory_service.resolve_set_members(
                db, record, include_addons
            )
            total = members["price_total"]
            if total <= 0:
                raise ClaimsError(
                    f"{record.name} has no purchase cost recorded — "
                    "enter an amount for this line instead."
                )
            return _money(total)
        if record.purchase_price is None:
            raise ClaimsError(
                f"{record.name} has no purchase price recorded — "
                "enter an amount for this line instead."
            )
        return _money(record.purchase_price * (record.quantity or 1))
    if target_kind == "set":
        if value_basis == "replacement":
            members = inventory_service.resolve_set_members(
                db, record, include_addons
            )
            return _money(members["replacement_total"])
        # msrp basis for a set: the set's own list price x quantity
        # (pieces carry prices, not MSRPs — there is nothing else
        # honest to add).
        if record.msrp is None:
            raise ClaimsError(
                f"{record.name} has no MSRP recorded — use the "
                "replacement value or enter an amount instead."
            )
        return _money(record.msrp * (record.quantity or 1))
    field = "replacement_cost" if value_basis == "replacement" else "msrp"
    value = getattr(record, field)
    if value is None:
        label = "replacement cost" if value_basis == "replacement" else "MSRP"
        raise ClaimsError(
            f"{record.name} has no {label} recorded — enter an amount "
            "for this line instead."
        )
    return _money(value * (record.quantity or 1))


def add_line(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    *,
    target_kind: str,
    target_id: uuid.UUID,
    include_addons: bool = False,
    value_basis: str = "purchase",
    amount=None,
    kind: str | None = None,
) -> models.ClaimLine:
    """Add a target to a DRAFT claim, priced and snapshotted. Once
    the claim is filed its contents are the insurer's record and
    stop moving. New lines price on the PURCHASE basis (what the
    owner paid) or carry the owner's entered figure — the schema
    refuses the retired replacement/MSRP bases at the door."""
    claim = _claim_or_404(db, owner.id, claim_id, kind=kind)
    if claim.status != models.STATUS_DRAFT:
        raise ClaimsError(
            "Items can only be added while the claim is a draft — "
            "a filed claim's contents are fixed."
        )
    record = _resolve_target(db, owner.id, target_kind, target_id)
    if record is None:
        raise ClaimsNotFound("That item isn't in your vault.")
    if target_kind == "tool" and record.is_set:
        raise ClaimsError(
            f"{record.name} is a set — add it as a set so you can "
            "choose whether its addons are included."
        )
    if target_kind == "set" and not record.is_set:
        raise ClaimsError(f"{record.name} isn't a set.")
    existing = db.scalars(
        select(models.ClaimLine).where(
            models.ClaimLine.claim_id == claim.id,
            models.ClaimLine.target_kind == target_kind,
            models.ClaimLine.target_id == target_id,
        )
    ).first()
    if existing is not None:
        raise ClaimsError(f"{record.name} is already on this claim.")

    line_amount = _line_amount(
        db,
        owner,
        target_kind=target_kind,
        record=record,
        include_addons=bool(include_addons) if target_kind == "set" else False,
        value_basis=value_basis,
        entered_amount=amount,
    )
    row = _insert_line(
        db,
        owner,
        claim,
        target_kind=target_kind,
        target_id=target_id,
        record=record,
        include_addons=bool(include_addons) if target_kind == "set" else False,
        value_basis=value_basis,
        line_amount=line_amount,
    )
    db.commit()
    db.refresh(row)
    return row


def _insert_line(
    db: Session,
    owner: core_models.User,
    claim: models.Claim,
    *,
    target_kind: str,
    target_id: uuid.UUID,
    record,
    include_addons: bool,
    value_basis: str,
    line_amount,
) -> models.ClaimLine:
    """The snapshot insert itself, shared by add_line (draft
    insurance claims, caller-checked) and the warranty
    quick-create (a claim born live with its one item already
    chosen). The amount arrives PRE-PRICED — pricing rules differ
    per flow; the snapshot never does. Does not commit."""
    set_id = None
    set_name = ""
    target_part_number = ""
    set_model_number = ""
    if target_kind == "set":
        set_id = record.id
        set_model_number = (record.model or "").strip()
    elif target_kind == "piece":
        set_id = record.set_id
        target_part_number = (record.part_number or "").strip()
        parent_set = inventory_service.get_tool(db, owner.id, record.set_id)
        if parent_set is not None:
            set_name = parent_set.name
            set_model_number = (parent_set.model or "").strip()
    row = models.ClaimLine(
        owner_id=owner.id,
        claim_id=claim.id,
        target_kind=target_kind,
        target_id=target_id,
        set_id=set_id,
        target_name=record.name,
        set_name=set_name,
        target_part_number=target_part_number,
        set_model_number=set_model_number,
        include_addons=bool(include_addons),
        value_basis=value_basis,
        amount=line_amount,
    )
    db.add(row)
    db.flush()
    return row


def remove_line(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    line_id: uuid.UUID,
    kind: str | None = None,
) -> bool:
    claim = _claim_or_404(db, owner.id, claim_id, kind=kind)
    if claim.status != models.STATUS_DRAFT:
        raise ClaimsError(
            "Items can only be removed while the claim is a draft."
        )
    row = db.get(models.ClaimLine, line_id)
    if row is None or row.claim_id != claim.id or row.owner_id != owner.id:
        return False
    db.delete(row)
    db.commit()
    return True


def _lines(db: Session, claim_id: uuid.UUID) -> list[models.ClaimLine]:
    return list(
        db.scalars(
            select(models.ClaimLine)
            .where(models.ClaimLine.claim_id == claim_id)
            .order_by(models.ClaimLine.created_at, models.ClaimLine.id)
        )
    )


def _line_display_name(line: models.ClaimLine) -> str:
    """How a line reads wherever claim items are named (dealer
    page, item page, notifications). A piece names itself, its
    parent set, and BOTH numbers when the snapshots carry them —
    Ryan 2026-10-25: a dealer sometimes can only find the piece
    by the set's model number."""
    name = line.target_name
    if line.target_kind == "piece" and line.set_name:
        name = f"{name} (piece of {line.set_name})"
        extras = []
        if line.target_part_number:
            extras.append(f"part {line.target_part_number}")
        if line.set_model_number:
            extras.append(f"set model {line.set_model_number}")
        if extras:
            name = f"{name} — " + ", ".join(extras)
    return name


def line_view(row: models.ClaimLine) -> dict:
    return {
        "id": row.id,
        "claim_id": row.claim_id,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "set_id": row.set_id,
        "target_name": row.target_name,
        "set_name": row.set_name,
        "target_part_number": row.target_part_number,
        "set_model_number": row.set_model_number,
        "include_addons": row.include_addons,
        "value_basis": row.value_basis,
        "amount": row.amount,
        "include_in_package": bool(row.include_in_package),
        "created_at": row.created_at,
    }


# -- evidence --------------------------------------------------------------------


def _require_open_for_evidence(claim: models.Claim) -> None:
    if _is_closed(claim):
        raise ClaimsError(
            f"Claim {claim.claim_number} is closed — its evidence is final."
        )


def _target_attachment_index(
    db: Session, owner_id: uuid.UUID, claim: models.Claim
) -> dict[tuple[str, uuid.UUID], object]:
    """(item_kind, item_id) -> inventory record for every item
    this claim's evidence may draw from: each line's target, plus
    — for a set line — the set's pieces (their receipts/photos are
    evidence for the set), plus a piece line's own piece."""
    index: dict[tuple[str, uuid.UUID], object] = {}
    for line in _lines(db, claim.id):
        if line.target_kind in ("tool", "battery"):
            record = _resolve_target(db, owner_id, line.target_kind, line.target_id)
            if record is not None:
                index[(line.target_kind, line.target_id)] = record
        elif line.target_kind == "set":
            record = _resolve_target(db, owner_id, "set", line.target_id)
            if record is not None:
                index[("tool", line.target_id)] = record
                members = inventory_service.resolve_set_members(
                    db, record, True, include_gone=True
                )
                for piece in list(members["core_pieces"]) + list(
                    members["addon_pieces"]
                ):
                    index[("piece", piece.id)] = piece
        elif line.target_kind == "piece":
            record = _resolve_target(db, owner_id, "piece", line.target_id)
            if record is not None:
                index[("piece", line.target_id)] = record
    return index


def _find_attachment(record, key: str) -> dict | None:
    for item in record.attachments or []:
        if isinstance(item, dict) and item.get("key") == key:
            return item
    return None


def add_evidence_reference(
    db: Session,
    actor: core_models.User,
    claim_id: uuid.UUID,
    *,
    item_kind: str,
    item_id: uuid.UUID,
    attachment_key: str,
    kind: str | None = None,
) -> models.ClaimEvidence:
    """Attach an item's EXISTING file to the claim by reference —
    the file is never copied. The item must be one of this claim's
    targets (evidence follows the lines); the filename/kind are
    snapshotted so the row stays readable if the file later leaves
    the item. Either party may add on a warranty claim (the
    dealer's photos of the repair are evidence too)."""
    claim, _role = _claim_for_actor(db, actor, claim_id, kind=kind)
    _require_open_for_evidence(claim)
    index = _target_attachment_index(db, claim.owner_id, claim)
    record = index.get((item_kind, item_id))
    if record is None:
        raise ClaimsError(
            "Evidence can only come from items on this claim — "
            "add the item to the claim first."
        )
    entry = _find_attachment(record, attachment_key)
    if entry is None:
        raise ClaimsError("That file isn't attached to this item.")
    duplicate = db.scalars(
        select(models.ClaimEvidence).where(
            models.ClaimEvidence.claim_id == claim.id,
            models.ClaimEvidence.source == "reference",
            models.ClaimEvidence.attachment_key == attachment_key,
        )
    ).first()
    if duplicate is not None:
        raise ClaimsError("That file is already on this claim.")
    row = models.ClaimEvidence(
        owner_id=claim.owner_id,
        claim_id=claim.id,
        source="reference",
        item_kind=item_kind,
        item_id=item_id,
        attachment_key=attachment_key,
        filename=entry.get("filename", ""),
        kind=entry.get("kind", "document"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _notify_evidence_added(db, claim, actor)
    return row


def issue_evidence_upload_url(
    db: Session,
    actor: core_models.User,
    claim_id: uuid.UUID,
    *,
    kind: str,
    filename: str,
    content_type: str,
    size_bytes: int | None = None,
    claim_kind: str | None = None,
) -> dict:
    """Claim-specific upload, step 1 (mirrors the inventory
    attachment flow exactly: kind + content-type allowlist, the
    kind's size cap, presigned PUT, bytes never touch the API).
    Keys stay namespaced to the CLAIM's owner even when a dealer
    party uploads — the file belongs to the claim's record.
    (`kind` here is the EVIDENCE kind; the section scope rides
    as `claim_kind` — claims separation, 2026-11-05.)"""
    claim, _role = _claim_for_actor(db, actor, claim_id, kind=claim_kind)
    _require_open_for_evidence(claim)
    if kind not in ALLOWED_CONTENT_TYPES:
        raise ClaimsError(
            f"kind must be one of {sorted(ALLOWED_CONTENT_TYPES)}"
        )
    content_type = content_type.lower().strip()
    if content_type not in ALLOWED_CONTENT_TYPES[kind]:
        raise ClaimsError(f"content_type '{content_type}' not allowed for {kind}")
    if size_bytes is not None:
        if size_bytes <= 0:
            raise ClaimsError("size_bytes must be positive")
        cap = inventory_attachments.max_bytes_for(kind)
        if size_bytes > cap:
            raise ClaimsError(
                f"File too large: {size_bytes} bytes (max {cap // (1024 * 1024)} MB)"
            )
    key = storage.object_key(
        str(claim.owner_id), str(claim.id), kind, filename, collection="claims"
    )
    try:
        url = storage.presigned_put_url(key, content_type)
    except StorageError as exc:
        raise ClaimsError(str(exc)) from exc
    return {"upload_url": url, "key": key, "expires_in": 900}


def attach_evidence_upload(
    db: Session,
    actor: core_models.User,
    claim_id: uuid.UUID,
    *,
    key: str,
    filename: str = "",
    kind: str | None = None,
) -> models.ClaimEvidence:
    """Claim-specific upload, step 2: HEAD-verify the object (real
    size + content type, key namespaced to this claim) and record
    it as the claim's own evidence file."""
    claim, _role = _claim_for_actor(db, actor, claim_id, kind=kind)
    _require_open_for_evidence(claim)
    expected_prefix = f"{claim.owner_id}/claims/{claim.id}/"
    if not key.startswith(expected_prefix):
        raise ClaimsError("Storage key does not belong to this claim.")
    try:
        stored = storage.head(key)
    except StorageError as exc:
        raise ClaimsError(str(exc)) from exc
    kind = key.split("/")[3]  # {owner}/claims/{id}/{kind}/...
    cap = inventory_attachments.max_bytes_for(kind)
    if stored.size_bytes > cap:
        raise ClaimsError(
            f"File too large: {stored.size_bytes} bytes (max {cap // (1024 * 1024)} MB)"
        )
    if stored.content_type not in ALLOWED_CONTENT_TYPES.get(kind, set()):
        raise ClaimsError(
            f"Uploaded content type '{stored.content_type}' not allowed for {kind}"
        )
    # Content sniff (deep audit F4-06): bytes must match the declared
    # type, not just claim it.
    try:
        storage.verify_content_matches(key, stored.content_type)
    except StorageError as exc:
        raise ClaimsError(str(exc)) from exc
    attachment = {
        "key": stored.key,
        "filename": filename or storage.safe_filename(key),
        "kind": kind,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "uploaded_at": _now().isoformat(),
    }
    row = models.ClaimEvidence(
        owner_id=claim.owner_id,
        claim_id=claim.id,
        source="upload",
        attachment_key=stored.key,
        filename=attachment["filename"],
        kind=kind,
        attachment=attachment,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _notify_evidence_added(db, claim, actor)
    return row


def remove_evidence(
    db: Session,
    actor: core_models.User,
    claim_id: uuid.UUID,
    evidence_id: uuid.UUID,
    kind: str | None = None,
) -> bool:
    """Removal stays the claim OWNER's act (a dealer party can add
    evidence, not take the customer's record apart)."""
    claim, role = _claim_for_actor(db, actor, claim_id, kind=kind)
    if role != "owner":
        return False
    _require_open_for_evidence(claim)
    row = db.get(models.ClaimEvidence, evidence_id)
    if row is None or row.claim_id != claim.id or row.owner_id != claim.owner_id:
        return False
    if row.source == "upload" and row.attachment:
        key = row.attachment.get("key")
        if key:
            # Tombstoned for the retention window (audit trail).
            journal.retire_keys(
                db, claim.owner_id, [key],
                entity_type="claim_evidence", entity_id=row.id,
            )
    db.delete(row)
    db.commit()
    return True


def _evidence_rows(db: Session, claim_id: uuid.UUID) -> list[models.ClaimEvidence]:
    return list(
        db.scalars(
            select(models.ClaimEvidence)
            .where(models.ClaimEvidence.claim_id == claim_id)
            .order_by(models.ClaimEvidence.created_at, models.ClaimEvidence.id)
        )
    )


def evidence_view(
    db: Session, owner_id: uuid.UUID, row: models.ClaimEvidence
) -> dict:
    """The wire shape. References resolve LIVE: the URL is minted
    fresh from the item's current attachment — and if the item or
    file is gone, `available` says so honestly (the snapshot
    filename keeps the row readable). Uploads resolve from the
    claim's own stored dict."""
    view = {
        "id": row.id,
        "claim_id": row.claim_id,
        "source": row.source,
        "item_kind": row.item_kind,
        "item_id": row.item_id,
        "attachment_key": row.attachment_key,
        "filename": row.filename,
        "kind": row.kind,
        "content_type": "",
        "size_bytes": 0,
        "url": None,
        "available": False,
        "created_at": row.created_at,
    }
    if row.source == "upload" and row.attachment:
        stored = row.attachment
        view.update(
            filename=stored.get("filename", row.filename),
            content_type=stored.get("content_type", ""),
            size_bytes=stored.get("size_bytes", 0),
            url=storage.presigned_get_url(stored["key"]),
            available=True,
        )
        return view
    if row.item_kind and row.item_id:
        record = None
        if row.item_kind == "tool":
            record = inventory_service.get_tool(db, owner_id, row.item_id)
        elif row.item_kind == "battery":
            record = inventory_service.get_battery(db, owner_id, row.item_id)
        elif row.item_kind == "piece":
            record = inventory_service.get_set_piece(db, owner_id, row.item_id)
        if record is not None:
            entry = _find_attachment(record, row.attachment_key)
            if entry is not None:
                view.update(
                    filename=entry.get("filename", row.filename),
                    content_type=entry.get("content_type", ""),
                    size_bytes=entry.get("size_bytes", 0),
                    url=storage.presigned_get_url(entry["key"]),
                    available=True,
                )
    return view


# -- communications log ----------------------------------------------------------


def _comm_or_404(
    db: Session, claim: models.Claim, entry_id: uuid.UUID
) -> models.ClaimCommunication:
    row = db.get(models.ClaimCommunication, entry_id)
    if row is None or row.claim_id != claim.id or row.owner_id != claim.owner_id:
        raise ClaimsNotFound("That log entry doesn't exist.")
    return row


def _require_open_for_comms(claim: models.Claim) -> None:
    if _is_closed(claim):
        raise ClaimsError(
            f"Claim {claim.claim_number} is closed — its log is final."
        )


def add_communication(
    db: Session,
    actor: core_models.User,
    claim_id: uuid.UUID,
    *,
    channel: str,
    contact: str = "",
    summary: str = "",
    occurred_at: datetime | None = None,
    kind: str | None = None,
) -> models.ClaimCommunication:
    """Add a log entry. On an insurance claim only the owner
    writes (the log is their record of dealing with the insurer).
    On a WARRANTY claim the log is the two-party record: the
    owner and the dealer side both write, each entry stamped
    with its author, and the other side hears about it."""
    claim, role = _claim_for_actor(db, actor, claim_id, kind=kind)
    _require_open_for_comms(claim)
    row = models.ClaimCommunication(
        owner_id=claim.owner_id,
        claim_id=claim.id,
        channel=channel,
        contact=(contact or "").strip(),
        summary=summary or "",
        occurred_at=_comm_moment(occurred_at) or _now(),
        author_id=actor.id,
        author_role=role,
        author_name=_actor_display_name(db, actor),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if claim.kind == models.KIND_WARRANTY:
        lines = _lines(db, claim.id)
        item_name = _line_display_name(lines[0]) if lines else "an item"
        _notify_warranty_activity(
            db,
            claim,
            actor.id,
            title=f"Warranty claim {claim.claim_number}",
            body=(
                f"{row.author_name} added a note to the claim for "
                f"{item_name}."
            ),
        )
    return row


def update_communication(
    db: Session,
    actor: core_models.User,
    claim_id: uuid.UUID,
    entry_id: uuid.UUID,
    kind: str | None = None,
    **changes,
) -> models.ClaimCommunication:
    """Edit an entry: its author, or the claim's owner (the
    record is theirs to keep straight)."""
    claim, role = _claim_for_actor(db, actor, claim_id, kind=kind)
    _require_open_for_comms(claim)
    row = _comm_or_404(db, claim, entry_id)
    if role != "owner" and row.author_id != actor.id:
        raise ClaimsNotFound("That log entry doesn't exist.")
    for key, value in changes.items():
        if key == "contact" and isinstance(value, str):
            value = value.strip()
        if key == "occurred_at":
            value = _comm_moment(value)
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def delete_communication(
    db: Session,
    actor: core_models.User,
    claim_id: uuid.UUID,
    entry_id: uuid.UUID,
    kind: str | None = None,
) -> bool:
    claim, role = _claim_for_actor(db, actor, claim_id, kind=kind)
    _require_open_for_comms(claim)
    row = db.get(models.ClaimCommunication, entry_id)
    if row is None or row.claim_id != claim.id or row.owner_id != claim.owner_id:
        return False
    if role != "owner" and row.author_id != actor.id:
        return False
    db.delete(row)
    db.commit()
    return True


def _comm_rows(db: Session, claim_id: uuid.UUID) -> list[models.ClaimCommunication]:
    return list(
        db.scalars(
            select(models.ClaimCommunication)
            .where(models.ClaimCommunication.claim_id == claim_id)
            .order_by(
                models.ClaimCommunication.occurred_at.desc(),
                models.ClaimCommunication.created_at.desc(),
            )
        )
    )


def comm_view(row: models.ClaimCommunication) -> dict:
    return {
        "id": row.id,
        "claim_id": row.claim_id,
        "channel": row.channel,
        "contact": row.contact,
        "summary": row.summary,
        "occurred_at": row.occurred_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        # Authorship (2026-10-25): "" role = a pre-split entry,
        # which is the owner's by definition.
        "author_id": row.author_id,
        "author_role": row.author_role or "owner",
        "author_name": row.author_name,
    }


# -- checklist + views --------------------------------------------------------------


def checklist(
    claim: models.Claim, line_count: int, evidence_count: int
) -> list[dict]:
    """The claim's todo list, COMPUTED from its contents (never
    stored, so it can never disagree with the claim). The police
    report item appears only for theft — the one case where the
    checklist treats it as required; the proof-of-loss item tracks
    the mark-sent action.

    A WARRANTY claim's list is its own short ladder: the item is
    on it (always true — warranty claims are born with their
    item), a dealer is recorded, the dealer has been told, and
    the repair/replacement is wrapped up."""
    if claim.kind == models.KIND_WARRANTY:
        # The told-someone step is about the AGENT when the claim
        # runs through one (2026-10-31) — its own checklist key, so
        # the page labels it "Agent notified"; a claim the owner
        # handles alone keeps the dealer wording.
        has_agent = (
            claim.agent_user_id is not None
            or claim.private_agent_id is not None
        )
        return [
            {
                "key": "items",
                "label": "Item added to the claim",
                "done": line_count > 0,
            },
            {
                "key": "dealer",
                "label": "Dealer recorded",
                "done": bool(claim.dealer_company_id or claim.dealer_name),
            },
            {
                "key": "reported_agent" if has_agent else "reported",
                "label": "Agent notified" if has_agent else "Dealer notified",
                "done": claim.status != models.STATUS_NOT_REPORTED,
            },
            {
                "key": "resolved",
                "label": "Repair or replacement completed",
                "done": claim.status == models.STATUS_COMPLETED
                or _is_closed(claim),
            },
        ]
    items = [
        {
            "key": "incident",
            "label": "Incident details complete",
            "done": bool(
                claim.incident_date is not None and claim.description.strip()
            ),
        },
        {
            "key": "items",
            "label": "Items added to the claim",
            "done": line_count > 0,
        },
        {
            "key": "evidence",
            "label": "Evidence attached (photos, documents, receipts)",
            "done": evidence_count > 0,
        },
    ]
    if claim.incident_type == "theft":
        items.append(
            {
                "key": "police_report",
                "label": "Police report added",
                "done": bool(claim.police_report_number.strip()),
            }
        )
    items.append(
        {
            "key": "proof_of_loss",
            "label": "Proof of loss sent to the insurer",
            "done": claim.proof_of_loss_sent_at is not None,
        }
    )
    return items


def claim_view(
    db: Session,
    owner: core_models.User,
    claim: models.Claim,
    viewer_role: str = "owner",
) -> dict:
    """The full detail picture: header, snapshotted lines,
    evidence, comms log, checklist, transitions, total.

    `owner` is always the CLAIM's owner (evidence storage and the
    repair seam key off them). `viewer_role` says who is LOOKING:
    the owner sees the full ladder; a dealer party on a warranty
    claim sees the same record with only the dealer moves offered
    — one record, two seats."""
    lines = _lines(db, claim.id)
    evidence = _evidence_rows(db, claim.id)
    items = checklist(claim, len(lines), len(evidence))
    if viewer_role == "dealer":
        allowed = list(
            models.DEALER_WARRANTY_TRANSITIONS.get(claim.status, ())
        )
    else:
        allowed = list(models.transitions_for(claim)[claim.status])
    if claim.kind == models.KIND_WARRANTY and claim.closed_at is not None:
        # A closed warranty claim is final (overhaul, 2026-11-06):
        # the closed layer offers no moves to either seat, even
        # though its preserved status still names a ladder rung.
        allowed = []
    return {
        "id": claim.id,
        "claim_number": claim.claim_number,
        "kind": claim.kind,
        "insurer_name": claim.insurer_name,
        "policy_number": claim.policy_number,
        "agent_name": claim.agent_name,
        "agent_phone": claim.agent_phone,
        "agent_email": claim.agent_email,
        # Warranty claims: the dealer block (id + name snapshot,
        # when the dealer was told and how).
        "dealer_company_id": claim.dealer_company_id,
        "dealer_name": claim.dealer_name,
        # The filed-with mode (overhaul, 2026-11-06): agent /
        # self / corporate — which of Ryan's three filing routes
        # the claim took, i.e. who its counterparty seat is.
        "filed_with": claim.filed_with or models.FILED_WITH_SELF,
        "reported_at": claim.reported_at,
        "report_method": claim.report_method,
        # The manufacturer's claim / case number (warranty only —
        # an insurance claim's stays empty; it has a policy
        # number instead) and the claim's AGENT (2026-10-31): the
        # one agent the claim runs through, or null. The owner's
        # seat also gets the pick list (their agents on record for
        # the dealer) so the page can re-point the claim.
        "manufacturer_case_number": claim.manufacturer_case_number,
        # The repair working end (merge, 2026-11-04): where the
        # item was sent, what the repair cost, when it finished —
        # carried ON the claim. Empty/None on insurance claims.
        "repair_sent_to": claim.repair_sent_to,
        "repair_cost": claim.repair_cost,
        "repair_completed_at": claim.repair_completed_at,
        "warranty_agent": (
            claim_agent_view(db, claim)
            if claim.kind == models.KIND_WARRANTY
            else None
        ),
        "agent_options": (
            agent_option_views(db, owner.id, claim.dealer_company_id)
            if claim.kind == models.KIND_WARRANTY and viewer_role == "owner"
            else []
        ),
        # Who is looking, and (for the dealer seat) who owns the
        # claim — the dealer needs the customer's name + email to
        # reach them about the repair.
        "viewer_role": viewer_role,
        "owner_name": owner.name,
        "owner_email": owner.email,
        # The amounts on this record are the owner's money: the
        # currency rides along so every surface labels them with
        # the OWNER's currency (the package already prints it),
        # never the viewer's.
        "owner_currency": core_money.normalize_currency(owner.currency),
        "incident_type": claim.incident_type,
        "incident_date": claim.incident_date,
        "description": claim.description,
        "status": claim.status,
        "police_report_number": claim.police_report_number,
        "police_department": claim.police_department,
        "police_report_date": claim.police_report_date,
        "proof_of_loss_due": claim.proof_of_loss_due,
        "proof_of_loss_sent_at": claim.proof_of_loss_sent_at,
        "depreciation_deadline": claim.depreciation_deadline,
        "filed_at": claim.filed_at,
        "closed_at": claim.closed_at,
        "archived": bool(claim.archived),
        "archived_at": claim.archived_at,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
        "lines": [line_view(r) for r in lines],
        "evidence": [evidence_view(db, owner.id, r) for r in evidence],
        "communications": [comm_view(r) for r in _comm_rows(db, claim.id)],
        "checklist": items,
        "checklist_done": sum(1 for i in items if i["done"]),
        "checklist_total": len(items),
        "total_amount": _money(
            sum((r.amount or Decimal("0")) for r in lines)
        ),
        "allowed_transitions": allowed,
    }


def claim_summary(
    db: Session, claim: models.Claim, owner_currency: str | None = None
) -> dict:
    """The list-row shape: header + counts + total, no children
    beyond what a list needs. The total is the owner's money, so
    the owner's currency rides along (callers who already hold
    the owner pass it; the rest resolve it here)."""
    if owner_currency is None:
        owner_row = db.get(core_models.User, claim.owner_id)
        owner_currency = owner_row.currency if owner_row is not None else ""
    lines = _lines(db, claim.id)
    evidence_count = db.scalar(
        select(func.count(models.ClaimEvidence.id)).where(
            models.ClaimEvidence.claim_id == claim.id
        )
    ) or 0
    items = checklist(claim, len(lines), int(evidence_count))
    agent_view = (
        claim_agent_view(db, claim)
        if claim.kind == models.KIND_WARRANTY
        else None
    )
    return {
        "id": claim.id,
        "claim_number": claim.claim_number,
        "kind": claim.kind,
        "dealer_name": claim.dealer_name,
        "filed_with": claim.filed_with or models.FILED_WITH_SELF,
        # The warranty claim's agent, by name ("" when none) — the
        # list rows name who the claim runs through (2026-10-31).
        "warranty_agent_name": agent_view["name"] if agent_view else "",
        "manufacturer_case_number": claim.manufacturer_case_number,
        # The repair facts ride the summary too (merge,
        # 2026-11-04): list rows and the item page's claim rows
        # can show "sent to X" / the repair cost without a
        # second fetch.
        "repair_sent_to": claim.repair_sent_to,
        "repair_cost": claim.repair_cost,
        "insurer_name": claim.insurer_name,
        "policy_number": claim.policy_number,
        "incident_type": claim.incident_type,
        "incident_date": claim.incident_date,
        "description": claim.description,
        "status": claim.status,
        "proof_of_loss_due": claim.proof_of_loss_due,
        "proof_of_loss_sent_at": claim.proof_of_loss_sent_at,
        "depreciation_deadline": claim.depreciation_deadline,
        "filed_at": claim.filed_at,
        # When the claim was reported to its dealer (warranty
        # claims are born with it) — the list's "Opened" date
        # (claims separation, 2026-11-05).
        "reported_at": claim.reported_at,
        "closed_at": claim.closed_at,
        "archived": bool(claim.archived),
        "archived_at": claim.archived_at,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
        "line_count": len(lines),
        "first_item_name": _line_display_name(lines[0]) if lines else "",
        "total_amount": _money(sum((r.amount or Decimal("0")) for r in lines)),
        # The repair working end (merge, 2026-11-04): the item
        # page's claim rows name where the item went and what
        # the repair cost, without opening the claim.
        "repair_sent_to": claim.repair_sent_to or "",
        "repair_cost": claim.repair_cost,
        "owner_currency": core_money.normalize_currency(owner_currency),
        "checklist_done": sum(1 for i in items if i["done"]),
        "checklist_total": len(items),
    }


def list_claims(
    db: Session,
    owner: core_models.User,
    include_archived: bool = False,
    kind: str | None = None,
) -> list[models.Claim]:
    """One section's claims list (claims separation, 2026-11-05:
    each section's route passes its own kind; the lists never
    mix). Archived claims leave the default list (wave 3) — they
    stay one filter away, never deleted."""
    stmt = (
        select(models.Claim)
        .where(models.Claim.owner_id == owner.id)
        .order_by(models.Claim.created_at.desc(), models.Claim.id.desc())
    )
    if kind is not None:
        stmt = stmt.where(models.Claim.kind == kind)
    if not include_archived:
        stmt = stmt.where(models.Claim.archived.is_(False))
    return list(db.scalars(stmt))


# -- dealer intermingling (2026-10-25) ---------------------------------------
#
# The dealer triangle: a claim reaches a dealer through its LINES'
# items — the item's dealer TAG (dealer_company_id) is the one
# canonical link, read LIVE. Claim lines snapshot names and values
# but never the dealer, so attribution follows the item's CURRENT
# tag: re-tagging an item re-attributes its claims, and a claim
# whose items were all deleted attributes to no dealer (the line
# survives; the dealer is unknowable). That is the honest read of
# the data the system holds — reported, never papered over.


def _item_dealer_maps(db: Session, owner_id: uuid.UUID):
    """({tool_id: dealer_company_id}, {battery_id: dealer_company_id})
    over the owner's items — one query per kind."""
    from app.modules.inventory import models as inv_models

    tools = {
        row_id: company_id
        for row_id, company_id in db.execute(
            select(inv_models.Tool.id, inv_models.Tool.dealer_company_id).where(
                inv_models.Tool.owner_id == owner_id
            )
        )
    }
    batteries = {
        row_id: company_id
        for row_id, company_id in db.execute(
            select(inv_models.Battery.id, inv_models.Battery.dealer_company_id).where(
                inv_models.Battery.owner_id == owner_id
            )
        )
    }
    return tools, batteries


def _line_dealer_id(line: models.ClaimLine, tools: dict, batteries: dict):
    """The dealer ONE claim line attributes to, via its item's
    live tag. Piece lines resolve through their parent set (the
    set carries the tag); a line whose item is gone attributes
    nowhere."""
    if line.target_kind in ("tool", "set"):
        return tools.get(line.target_id)
    if line.target_kind == "battery":
        return batteries.get(line.target_id)
    if line.target_kind == "piece":
        return tools.get(line.set_id) or tools.get(line.target_id)
    return None


def _dealer_names(db: Session, company_ids, owner_id=None) -> dict:
    """{company_id: name}. `owner_id` (personal dealer edits,
    2026-11-05): the names resolve through the CLAIM OWNER's
    personal layer when the caller knows it — claim surfaces
    show their owner the name he keeps for that dealer.
    Agent-facing reads pass no owner and keep the shared
    directory name."""
    wanted = {cid for cid in company_ids if cid is not None}
    if not wanted:
        return {}
    from app.modules.dealers import models as dealer_models

    names = {
        row_id: name
        for row_id, name in db.execute(
            select(
                dealer_models.DealerCompany.id, dealer_models.DealerCompany.name
            ).where(dealer_models.DealerCompany.id.in_(wanted))
        )
    }
    if owner_id is not None:
        from app.modules.dealers import service as dealer_service

        names.update(dealer_service.personal_name_map(db, owner_id, wanted))
    return names


def dealers_for_claims(
    db: Session, owner_id: uuid.UUID, claims: list[models.Claim]
) -> dict:
    """{claim_id: [{id, name}, ...]} — every dealer a claim
    touches through its items' tags, name-sorted. Batch: one pass
    over the claims' lines, one over the owner's items, one over
    the companies — never a query per claim."""
    if not claims:
        return {}
    claim_ids = [c.id for c in claims]
    lines = list(
        db.scalars(
            select(models.ClaimLine).where(
                models.ClaimLine.claim_id.in_(claim_ids)
            )
        )
    )
    tools, batteries = _item_dealer_maps(db, owner_id)
    per_claim: dict[uuid.UUID, set] = {}
    for line in lines:
        company_id = _line_dealer_id(line, tools, batteries)
        if company_id is not None:
            per_claim.setdefault(line.claim_id, set()).add(company_id)
    names = _dealer_names(
        db, [cid for ids in per_claim.values() for cid in ids], owner_id
    )
    return {
        claim_id: [
            {"id": cid, "name": names.get(cid, "")}
            for cid in sorted(ids, key=lambda c: (names.get(c, "").lower(), str(c)))
        ]
        for claim_id, ids in per_claim.items()
    }


def _is_current(claim: models.Claim) -> bool:
    """Current = still in flight for ITS KIND, not shelved.
    Insurance: not at a terminal status (denied/paid/closed).
    Warranty: not Repaired and not closed — Repaired is the
    ladder's terminal (a finished repair is history, as ever),
    and the closed layer (overhaul, 2026-11-06) puts a claim
    away from ANY status, so a stamped closed_at also ends
    "current". History = terminal/closed per kind, or archived
    whatever its status (archiving is the owner's own act of
    putting a claim away)."""
    if claim.archived:
        return False
    if claim.kind == models.KIND_WARRANTY:
        return (
            claim.status
            not in (models.STATUS_COMPLETED, models.STATUS_CLOSED)
            and claim.closed_at is None
        )
    return not models.is_terminal(claim)


def _claim_ref(
    claim: models.Claim,
    lines: list[models.ClaimLine],
    item_names,
    owner_currency: str | None,
) -> dict:
    """The slim claim shape the dealer and item pages render:
    enough to recognize the claim and click through to it. The
    total is the owner's money, so the owner's currency rides
    along (every ref in a split belongs to the one owner)."""
    return {
        "id": claim.id,
        "claim_number": claim.claim_number,
        "kind": claim.kind,
        "dealer_name": claim.dealer_name,
        "filed_with": claim.filed_with or models.FILED_WITH_SELF,
        "status": claim.status,
        "insurer_name": claim.insurer_name,
        "incident_type": claim.incident_type,
        "incident_date": claim.incident_date,
        "total_amount": _money(sum((r.amount or Decimal("0")) for r in lines)),
        # The repair working end (merge, 2026-11-04): the item
        # page's claim rows name where the item went and what
        # the repair cost, without opening the claim.
        "repair_sent_to": claim.repair_sent_to or "",
        "repair_cost": claim.repair_cost,
        "owner_currency": core_money.normalize_currency(owner_currency),
        "created_at": claim.created_at,
        # The dealer page's claim rows (dealer page pass,
        # 2026-11-06): the claim date reads reported-or-filed,
        # exactly as the Repair claims list shows it, and the
        # last-update column reads the record's own stamp.
        "reported_at": claim.reported_at,
        "updated_at": claim.updated_at,
        "archived": bool(claim.archived),
        "items": list(item_names),
    }


def _split_claims(
    db: Session, claims: list[models.Claim], names_for, owner_currency: str | None
) -> dict:
    """{current: [...], history: [...]} of claim refs for a set of
    claims. `names_for(claim, lines)` picks the item names each
    ref carries. Current runs newest first; history runs by
    close date (filing date when unclosed) newest first."""
    current: list[dict] = []
    history: list[tuple[object, dict]] = []
    for claim in claims:
        lines = _lines(db, claim.id)
        ref = _claim_ref(claim, lines, names_for(claim, lines), owner_currency)
        if _is_current(claim):
            current.append(ref)
        else:
            history.append((claim.closed_at or claim.created_at, ref))
    current.sort(key=lambda r: r["created_at"], reverse=True)
    history.sort(key=lambda pair: pair[0], reverse=True)
    return {"current": current, "history": [ref for _when, ref in history]}


def claims_for_dealer(
    db: Session, owner: core_models.User, company_id: uuid.UUID
) -> dict:
    """Every claim of the owner's — EITHER kind — that touches
    this dealer (through any line's item tag), split
    current/history. Each ref names only THIS dealer's items on
    the claim (the line snapshots), so the dealer page shows
    what of theirs is on it. This is the DEALER's record surface
    (the dealers API's my-records block), not a claims-section
    surface: the two-types model puts every claim whose lines
    resolve to the company on the dealer's page in full, and the
    separation splits the two claim SECTIONS, not the dealer's
    facts. Each ref carries its kind and the page links it into
    its own section (claims separation, 2026-11-05)."""
    claims = list(
        db.scalars(
            select(models.Claim).where(models.Claim.owner_id == owner.id)
        )
    )
    if not claims:
        return {"current": [], "history": []}
    tools, batteries = _item_dealer_maps(db, owner.id)
    lines_by_claim: dict[uuid.UUID, list[models.ClaimLine]] = {}
    for line in db.scalars(
        select(models.ClaimLine).where(
            models.ClaimLine.claim_id.in_([c.id for c in claims])
        )
    ):
        lines_by_claim.setdefault(line.claim_id, []).append(line)

    def names_for(claim: models.Claim, _lines_: list[models.ClaimLine]):
        seen: list[str] = []
        for line in lines_by_claim.get(claim.id, []):
            if _line_dealer_id(line, tools, batteries) == company_id:
                display = _line_display_name(line)
                if display and display not in seen:
                    seen.append(display)
        return seen

    touching = [
        claim
        for claim in claims
        if any(
            _line_dealer_id(line, tools, batteries) == company_id
            for line in lines_by_claim.get(claim.id, [])
        )
    ]
    return _split_claims(db, touching, names_for, owner.currency)


def claims_for_item(
    db: Session, owner: core_models.User, kind: str, item_id: uuid.UUID
) -> dict:
    """Every claim carrying THIS item, split current/history —
    the item page's corner of the triangle. A tool matches its own
    lines, its set lines, and piece lines filed against it as a
    set; a battery matches its battery lines. Raises
    ClaimsNotFound when the item isn't the owner's (the page
    asking is the owner's own item page, so a foreign id is a
    plain not-found, never a leak)."""
    from app.modules.inventory import models as inv_models

    model = inv_models.Tool if kind == "tool" else inv_models.Battery
    item = db.get(model, item_id)
    if item is None or item.owner_id != owner.id:
        raise ClaimsNotFound("That item doesn't exist.")

    def line_matches(line: models.ClaimLine) -> bool:
        if kind == "tool":
            if line.target_kind in ("tool", "set"):
                return line.target_id == item_id
            if line.target_kind == "piece":
                return line.set_id == item_id
            return False
        return line.target_kind == "battery" and line.target_id == item_id

    lines = list(
        db.scalars(
            select(models.ClaimLine).where(models.ClaimLine.owner_id == owner.id)
        )
    )
    claim_ids = {line.claim_id for line in lines if line_matches(line)}
    if not claim_ids:
        return {"current": [], "history": []}
    claims = list(
        db.scalars(
            select(models.Claim).where(
                models.Claim.id.in_(claim_ids),
                models.Claim.owner_id == owner.id,
                # The item page's claim corner is the WARRANTY
                # section's (claims separation, 2026-11-05): a
                # disaster claim's hold on this item lives in the
                # Disaster Claims section, never here.
                models.Claim.kind == models.KIND_WARRANTY,
            )
        )
    )

    def names_for(_claim: models.Claim, claim_lines: list[models.ClaimLine]):
        seen: list[str] = []
        for line in claim_lines:
            display = _line_display_name(line)
            if display and display not in seen:
                seen.append(display)
        return seen

    return _split_claims(db, claims, names_for, owner.currency)


def get_claim(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    kind: str | None = None,
) -> models.Claim:
    return _claim_or_404(db, owner.id, claim_id, kind=kind)


# -- the agent side of a warranty claim (agent scope, 2026-10-31) -------------
#
# A warranty claim names a DEALER (the item's tag at creation —
# factual context) and at most ONE AGENT (the owner's dealer
# agent for the claim). The claim is a two-party record only when
# that agent is reachable on the platform: the agent pointer
# resolves to a platform user (directly, or through a private
# record the owner linked to an account) AND that user holds a
# VERIFIED representation of the claim's dealer (H-1 at agent
# level: a self-claimed, unverified representation gets nothing).
# The COMPANY as such is never a party — its other agents, its
# principal, its dashboard see none of it. An agent the owner
# typed in privately (no account, or no verified link) means the
# claim has no second viewer: the owner drives it by hand and the
# system holds the history (Ryan's model), with the owner's
# dealer page still showing every claim that touches the company
# (claims_for_dealer above — the owner's own records).


def _actor_display_name(db: Session, user: core_models.User) -> str:
    """How a notification names this user: their dealer display
    name when they have one (agents trade under it), else their
    account name."""
    try:
        from app.modules.dealers import portal as dealer_portal

        profile = dealer_portal.get_profile(db, user.id)
        if profile is not None and profile.display_name:
            return profile.display_name
    except Exception:  # a name lookup must never break an event
        pass
    return user.name


def agent_on_record(
    db: Session, owner_id: uuid.UUID, company_id: uuid.UUID | None
) -> tuple[uuid.UUID | None, uuid.UUID | None] | None:
    """The owner's agent ON RECORD for a dealer: (agent_user_id,
    private_agent_id) of the DISPLAY-DEFAULT preferred agent
    — the EARLIEST connection row flagged is_preferred for
    (owner, company) (multi-preferred, 2026-11-05: several rows
    may be flagged; exactly one of the pair is set — the
    PreferredAgent shape). Falls back to the EARLIEST connection
    row when none is flagged (rows written before the flag
    existed resolve exactly as they did pre-flag), and returns
    None when the owner has no agent for that dealer at all.
    This is the default a new warranty claim takes, the truck
    holder resolution, and the wizard's charge agent — every
    "agent on record" consumer reads through here."""
    if company_id is None:
        return None
    from app.modules.dealers import models as dealer_models

    row = db.scalars(
        select(dealer_models.PreferredAgent)
        .where(
            dealer_models.PreferredAgent.user_id == owner_id,
            dealer_models.PreferredAgent.company_id == company_id,
        )
        .order_by(
            dealer_models.PreferredAgent.is_preferred.desc(),
            dealer_models.PreferredAgent.created_at.asc(),
            dealer_models.PreferredAgent.id.asc(),
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    return row.agent_user_id, row.private_agent_id


def preferred_agents_for(
    db: Session, owner_id: uuid.UUID, company_id: uuid.UUID | None
) -> list[tuple[uuid.UUID | None, uuid.UUID | None]]:
    """Every (agent_user_id, private_agent_id) the owner has on
    record for a dealer, earliest first — the picker's universe
    for a claim's agent: a claim may only be pointed at an agent
    the owner actually has recorded for that dealer."""
    if company_id is None:
        return []
    from app.modules.dealers import models as dealer_models

    rows = db.scalars(
        select(dealer_models.PreferredAgent)
        .where(
            dealer_models.PreferredAgent.user_id == owner_id,
            dealer_models.PreferredAgent.company_id == company_id,
        )
        .order_by(
            dealer_models.PreferredAgent.created_at.asc(),
            dealer_models.PreferredAgent.id.asc(),
        )
    )
    return [(row.agent_user_id, row.private_agent_id) for row in rows]


def assigned_agent_user_id(
    db: Session, claim: models.Claim
) -> uuid.UUID | None:
    """The platform user a claim's agent pointer resolves to:
    the pointer itself when it names a platform agent, else the
    account the owner linked the private record to (the private
    -> platform switch), else None — an off-system agent."""
    if claim.agent_user_id is not None:
        return claim.agent_user_id
    if claim.private_agent_id is not None:
        from app.modules.dealers import models as dealer_models

        record = db.get(dealer_models.PrivateAgent, claim.private_agent_id)
        if record is not None:
            return record.linked_user_id
    return None


def agent_has_access(db: Session, claim: models.Claim) -> bool:
    """Whether the claim's assigned agent can actually see and
    work it from their seat. The seat's link to the claim's agent
    record must be VERIFIED — the basis differs by pointer type:

    - PLATFORM pointer: an ACTIVE user holding a VERIFIED
      representation of the claim's dealer (operator-verified).
    - PRIVATE pointer: the same verified-representation rule,
      PLUS the takeover state (owner model, 2026-11-03) — the
      record was claimed through its agent code WITH the owner's
      explicit acceptance of that account (link_source
      "takeover"). The owner's acceptance of a named account,
      gated on their secret code, IS the verification for this
      one customer relationship; it confers no company-level
      standing whatsoever (H-1 stays shut: nobody reaches a
      claim without a verified link to ITS agent record).
    Anything less — no pointer, an off-system agent, an
    unverified self-claimed representation — and the claim is
    the owner's alone (H-1, agent level)."""
    if claim.dealer_company_id is None:
        return False
    user_id = assigned_agent_user_id(db, claim)
    if user_id is None:
        return False
    user = db.get(core_models.User, user_id)
    if user is None or not user.is_active:
        return False
    from app.modules.dealers import models as dealer_models

    if claim.private_agent_id is not None:
        record = db.get(dealer_models.PrivateAgent, claim.private_agent_id)
        if (
            record is not None
            and not record.archived
            and record.link_source == "takeover"
            and record.linked_user_id == user_id
        ):
            return True
    verified = db.scalars(
        select(dealer_models.CompanyRepresentation.id).where(
            dealer_models.CompanyRepresentation.agent_user_id == user_id,
            dealer_models.CompanyRepresentation.company_id
            == claim.dealer_company_id,
            dealer_models.CompanyRepresentation.verified.is_(True),
        )
    ).first()
    return verified is not None


def claim_party_user_ids(db: Session, claim: models.Claim) -> set[uuid.UUID]:
    """The claim's second seat, as a set of platform user ids:
    the assigned agent's account, when the agent link is live
    (agent_has_access). Empty in every other case — the company
    contributes NOBODY under the agent-scope model."""
    if not agent_has_access(db, claim):
        return set()
    user_id = assigned_agent_user_id(db, claim)
    return {user_id} if user_id is not None else set()


def verified_rep_user_ids(
    db: Session, company_id: uuid.UUID | None
) -> set[uuid.UUID]:
    """Every ACTIVE platform user holding a VERIFIED
    representation of a dealer company — the corporate seat's
    population (claims overhaul, 2026-11-06). The representation
    machinery is the dealers module's (operator-verified links);
    an unverified self-claim confers nothing, exactly as with
    the agent seat (H-1)."""
    if company_id is None:
        return set()
    from app.modules.dealers import models as dealer_models

    ids: set[uuid.UUID] = set()
    for user_id in db.scalars(
        select(dealer_models.CompanyRepresentation.agent_user_id).where(
            dealer_models.CompanyRepresentation.company_id == company_id,
            dealer_models.CompanyRepresentation.verified.is_(True),
        )
    ):
        user = db.get(core_models.User, user_id)
        if user is not None and user.is_active:
            ids.add(user_id)
    return ids


def corporate_party_user_ids(
    db: Session, claim: models.Claim
) -> set[uuid.UUID]:
    """The corporate seat on ONE claim: the verified reps of the
    claim's dealer company — and ONLY when the claim was filed
    corporate. Agent- and self-filed claims return nobody here,
    however many verified reps the company has: the company seat
    never reaches across filing modes."""
    if claim.kind != models.KIND_WARRANTY:
        return set()
    if claim.filed_with != models.FILED_WITH_CORPORATE:
        return set()
    return verified_rep_user_ids(db, claim.dealer_company_id)


def claim_counterparty_user_ids(
    db: Session, claim: models.Claim
) -> set[uuid.UUID]:
    """The claim's seated counterparty, whoever the filed-with
    mode says it is: the verified agent on an agent-filed claim,
    the company's verified reps on a corporate-filed claim,
    nobody on a self-filed claim. This is THE seat resolution —
    access checks and notifications both read it, so a seat can
    never see a claim it isn't told about or be told about a
    claim it cannot open. The two halves are disjoint by
    construction: a corporate claim carries no agent pointer,
    and the corporate half answers only for corporate claims."""
    return claim_party_user_ids(db, claim) | corporate_party_user_ids(
        db, claim
    )


def claim_agent_view(db: Session, claim: models.Claim) -> dict | None:
    """The claim's agent, as every surface renders it: who they
    are, how to reach them, and whether their seat is live
    (has_access). None when the claim has no agent. A platform
    agent reads through their agent profile (display name +
    public contact, the profile's own choice); a private agent
    reads from the owner's own record."""
    from app.modules.dealers import models as dealer_models

    if claim.private_agent_id is not None:
        record = db.get(dealer_models.PrivateAgent, claim.private_agent_id)
        if record is None:
            return None
        return {
            "kind": "private",
            "agent_user_id": None,
            "private_agent_id": record.id,
            "name": record.name,
            "phone": record.phone,
            "email": record.email,
            "account_number": None,
            "has_access": agent_has_access(db, claim),
        }
    if claim.agent_user_id is not None:
        user = db.get(core_models.User, claim.agent_user_id)
        if user is None:
            return None
        name = _actor_display_name(db, user)
        phone = ""
        email = ""
        try:
            from app.modules.dealers import portal as dealer_portal

            profile = dealer_portal.get_profile(db, user.id)
            if profile is not None:
                phone = profile.phone or ""
                email = profile.contact_email or ""
        except Exception:  # a profile read must never break a view
            pass
        return {
            "kind": "platform",
            "agent_user_id": user.id,
            "private_agent_id": None,
            "name": name,
            "phone": phone,
            "email": email,
            "account_number": user.account_number,
            "has_access": agent_has_access(db, claim),
        }
    if claim.agent_name_snapshot:
        # The private record this claim was seated with was
        # deleted; the name was snapshotted onto the claim so it
        # still reads as that agent's work (stage 1, 2026-11-04).
        # No seat survives — nobody can open it from an agent side.
        return {
            "kind": "snapshot",
            "agent_user_id": None,
            "private_agent_id": None,
            "name": claim.agent_name_snapshot,
            "phone": "",
            "email": "",
            "account_number": None,
            "has_access": False,
        }
    return None


def agent_option_views(
    db: Session, owner_id: uuid.UUID, company_id: uuid.UUID | None
) -> list[dict]:
    """The owner's agents on record for a dealer, view-shaped —
    the pick list for a claim's agent (filing default + the claim
    page's re-point control), earliest first (the agent on record
    leads). Each view is claim_agent_view's shape, resolved
    against a probe pointer so access reads exactly as it would
    on a claim pointed there."""
    views = []
    for pair in preferred_agents_for(db, owner_id, company_id):
        probe = models.Claim(
            owner_id=owner_id,
            dealer_company_id=company_id,
            agent_user_id=pair[0],
            private_agent_id=pair[1],
        )
        view = claim_agent_view(db, probe)
        if view is not None:
            views.append(view)
    return views


def dealer_party_user_ids(db: Session, claim: models.Claim) -> set[uuid.UUID]:
    """Back-compat alias — the pre-2026-10-31 name for the claim's
    second seat. Under agent scope it is exactly the assigned,
    verified agent (claim_party_user_ids); the company-wide party
    set it used to return no longer exists."""
    return claim_party_user_ids(db, claim)


def claims_seated_with_agent(
    db: Session,
    owner_id: uuid.UUID,
    *,
    agent_user_id: uuid.UUID | None = None,
    private_agent_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    open_only: bool = False,
) -> list[models.Claim]:
    """The owner's warranty claims seated with ONE agent (the
    roster's per-agent claim list, and the preferred switch's
    prompt population when open_only). Open claims first, then
    newest — the order a person scans them in."""
    query = select(models.Claim).where(
        models.Claim.owner_id == owner_id,
        models.Claim.kind == models.KIND_WARRANTY,
    )
    if agent_user_id is not None:
        query = query.where(models.Claim.agent_user_id == agent_user_id)
    if private_agent_id is not None:
        query = query.where(models.Claim.private_agent_id == private_agent_id)
    if agent_user_id is None and private_agent_id is None:
        return []
    if company_id is not None:
        query = query.where(models.Claim.dealer_company_id == company_id)
    if open_only:
        # Open = in flight and not closed (the closed layer,
        # 2026-11-06): a claim closed from an open status keeps
        # that status, so the layer rides the filter too.
        query = query.where(
            models.Claim.status.in_(models.WARRANTY_OPEN_STATUSES),
            models.Claim.closed_at.is_(None),
        )
    rows = list(db.scalars(query))
    rows.sort(
        key=lambda c: (
            not (
                c.status in models.WARRANTY_OPEN_STATUSES
                and c.closed_at is None
            ),
            -(c.created_at.timestamp() if c.created_at else 0),
        )
    )
    return rows


def repoint_claims_from_private_record(
    db: Session,
    owner_id: uuid.UUID,
    private_agent_id: uuid.UUID,
    agent_user_id: uuid.UUID,
) -> int:
    """The private -> platform LINK is an identity merge, not an
    agent change (stage 1, 2026-11-04): the owner declares "this
    record IS that account", so the claims seated with the record
    — they were always that agent's claims, filed against his
    stand-in — seat with the account. Scoped to claims seated at
    THIS record only; nothing else moves. Returns how many."""
    claims = db.scalars(
        select(models.Claim).where(
            models.Claim.owner_id == owner_id,
            models.Claim.kind == models.KIND_WARRANTY,
            models.Claim.private_agent_id == private_agent_id,
        )
    )
    moved = 0
    for claim in claims:
        claim.agent_user_id = agent_user_id
        claim.private_agent_id = None
        moved += 1
    if moved:
        db.commit()
    return moved


def detach_claims_from_private_agent(
    db: Session, private_agent_id: uuid.UUID, name: str
) -> int:
    """Detach every claim seated with a private record that is
    being deleted (stage 1, 2026-11-04): the record's NAME is
    stamped onto each claim (agent_name_snapshot — the claims
    keep reading as his) and the pointer is cleared as an ORM
    write, the codebase's journal-first doctrine; the FK's
    SET NULL remains the backstop. Called by the dealers delete
    flow BEFORE the record goes; commits with it there, so this
    only flushes."""
    claims = db.scalars(
        select(models.Claim).where(
            models.Claim.kind == models.KIND_WARRANTY,
            models.Claim.private_agent_id == private_agent_id,
        )
    )
    detached = 0
    for claim in claims:
        claim.agent_name_snapshot = name
        claim.private_agent_id = None
        detached += 1
    db.flush()
    return detached


def _claim_for_actor(
    db: Session,
    actor: core_models.User,
    claim_id: uuid.UUID,
    kind: str | None = None,
) -> tuple[models.Claim, str]:
    """(claim, role) for whoever is acting: "owner" for the
    claim's owner, "dealer" for the claim's seated COUNTERPARTY
    on a warranty claim (the seat's standing name) — the assigned
    verified agent on an agent-filed claim, or a verified
    corporate rep on a corporate-filed claim (claims overhaul,
    2026-11-06: the one designed exception to "the company is
    never a party", and only for claims filed TO the company).
    Anyone else gets the same not-found as a stranger — a claim's
    existence is never leaked across accounts. `kind` is the
    section scope (claims separation, 2026-11-05): a claim of the
    other kind is equally not-found here, whichever section is
    asking."""
    claim = db.get(models.Claim, claim_id)
    if claim is None:
        raise ClaimsNotFound("That claim doesn't exist.")
    if kind is not None and claim.kind != kind:
        raise ClaimsNotFound("That claim doesn't exist.")
    if claim.owner_id == actor.id:
        return claim, "owner"
    if (
        claim.kind == models.KIND_WARRANTY
        and actor.id in claim_counterparty_user_ids(db, claim)
    ):
        return claim, "dealer"
    raise ClaimsNotFound("That claim doesn't exist.")


def get_claim_for_viewer(
    db: Session,
    viewer: core_models.User,
    claim_id: uuid.UUID,
    kind: str | None = None,
) -> tuple[models.Claim, core_models.User, str]:
    """(claim, claim's owner user, viewer's role) for the detail
    page — the one read both seats share."""
    claim, role = _claim_for_actor(db, viewer, claim_id, kind=kind)
    owner = db.get(core_models.User, claim.owner_id)
    return claim, owner, role


def _validate_agent_choice(
    db: Session,
    owner_id: uuid.UUID,
    company_id: uuid.UUID | None,
    agent_user_id: uuid.UUID | None,
    private_agent_id: uuid.UUID | None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Check an owner-picked agent for a claim under `company_id`
    and return the (agent_user_id, private_agent_id) pair to
    store. The pick must be one of the owner's agents ON RECORD
    for that dealer (a preferred-agent row) — a claim never points
    at an agent the owner hasn't recorded for the dealer, and
    never at both halves of the pair."""
    if agent_user_id is not None and private_agent_id is not None:
        raise ClaimsError(
            "A claim runs through one agent — pick the agent, not both."
        )
    if agent_user_id is None and private_agent_id is None:
        return None, None
    if company_id is None:
        raise ClaimsError(
            "This claim has no dealer, so there's no agent to run it "
            "through — it stays yours to handle."
        )
    if (agent_user_id, private_agent_id) not in preferred_agents_for(
        db, owner_id, company_id
    ):
        raise ClaimsError(
            "That agent isn't one of your agents on record for this "
            "dealer — add them on the dealer's page first."
        )
    return agent_user_id, private_agent_id


def set_claim_agent(
    db: Session,
    owner: core_models.User,
    claim_id: uuid.UUID,
    *,
    agent_user_id: uuid.UUID | None,
    private_agent_id: uuid.UUID | None,
) -> models.Claim:
    """Re-point a warranty claim at a different agent (or at no
    agent) — the owner's hand on the routing, and it HOLDS:
    nothing moves a claim's seat silently (stage 1, 2026-11-04;
    the 2026-10-31 follow sweep is retired — switching the
    preferred agent asks about each open claim instead). The
    previous agent loses the claim the moment this lands; the
    new agent gains it only when their link is verified
    (agent_has_access decides at read time, always)."""
    claim = _claim_or_404(db, owner.id, claim_id)
    if claim.kind != models.KIND_WARRANTY:
        raise ClaimsError(
            "Only a warranty claim runs through a dealer agent — an "
            "insurance claim is yours and your insurer's."
        )
    if _is_closed(claim):
        raise ClaimsError(
            f"Claim {claim.claim_number} is closed — its record is final."
        )
    pair = _validate_agent_choice(
        db, owner.id, claim.dealer_company_id, agent_user_id, private_agent_id
    )
    claim.agent_user_id, claim.private_agent_id = pair
    # The filed-with mode rides WITH the seat (overhaul,
    # 2026-11-06): pointing the claim at an agent makes it an
    # agent-filed claim; clearing the agent makes it the owner's
    # alone — including pulling a corporate-filed claim back from
    # the company, which is exactly what re-pointing it means.
    claim.filed_with = (
        models.FILED_WITH_AGENT
        if pair != (None, None)
        else models.FILED_WITH_SELF
    )
    db.commit()
    db.refresh(claim)
    return claim


def warranty_filing_options(
    db: Session,
    owner: core_models.User,
    *,
    target_kind: str,
    target_id: uuid.UUID,
) -> dict:
    """The broken-item form's agent step, resolved for one
    target: the dealer the claim will name (the item's tag; a
    piece answers to its parent set's) and the owner's agents on
    record for that dealer — the pick list, with the default (the
    earliest, i.e. the agent on record) flagged. No dealer on the
    item = no agents to pick from: the claim will be the owner's
    alone."""
    record = _resolve_target(db, owner.id, target_kind, target_id)
    if record is None:
        raise ClaimsNotFound("That item isn't in your vault.")
    company_id, dealer_name = _dealer_for_target(
        db, owner.id, target_kind, record, personal=True
    )
    default = agent_on_record(db, owner.id, company_id)
    return {
        "dealer_company_id": company_id,
        "dealer_name": dealer_name,
        "agents": agent_option_views(db, owner.id, company_id),
        "default_agent_user_id": default[0] if default else None,
        "default_private_agent_id": default[1] if default else None,
    }


def _notify_warranty_activity(
    db: Session,
    claim: models.Claim,
    actor_id: uuid.UUID,
    *,
    title: str,
    body: str,
    kind: str | None = None,
) -> None:
    """Tell the OTHER side of a warranty claim something
    happened: the owner hears about the counterparty's actions,
    the seated counterparty hears about the owner's, and nobody
    hears about their own. The counterparty is a recipient ONLY
    when their seat is live (claim_counterparty_user_ids — the
    verified agent, or the verified corporate reps on a
    corporate-filed claim) — a notification about a claim they
    cannot open would leak its existence and dead-end. Inbox
    only — its email twin rides the recipient's own notification
    preferences, like every cross-party event."""
    recipients: set[uuid.UUID] = set()
    if actor_id != claim.owner_id:
        recipients.add(claim.owner_id)
    recipients |= {
        uid
        for uid in claim_counterparty_user_ids(db, claim)
        if uid != actor_id
    }
    for uid in recipients:
        inbox.create_notification(
            db,
            uid,
            kind=kind or inbox.KIND_WARRANTY_CLAIM_UPDATE,
            title=title,
            body=body,
            data={"claim_id": str(claim.id)},
        )


def _notify_evidence_added(
    db: Session, claim: models.Claim, actor: core_models.User
) -> None:
    if claim.kind != models.KIND_WARRANTY:
        return
    lines = _lines(db, claim.id)
    item_name = _line_display_name(lines[0]) if lines else "an item"
    _notify_warranty_activity(
        db,
        claim,
        actor.id,
        title=f"Warranty claim {claim.claim_number}",
        body=(
            f"{_actor_display_name(db, actor)} added a file to the "
            f"claim for {item_name}."
        ),
    )


# -- per-target race guard (deep audit round 2, B-02/B-03) -------------------
#
# The one-open-warranty-claim-per-target rule and the
# never-replace-an-already-replaced-item rule are both
# check-then-act rules: two parallel requests could each pass
# the check before either one committed, and both would act
# (the audit's triple-click made 3 claims and 3 replacement
# tools). The checks therefore run under a per-target lock.
#
# The lock is a Postgres SESSION-level advisory lock, taken on a
# DEDICATED connection held for the whole call: the flows below
# commit several times mid-flight (claim create, clone, retire),
# and a transaction-level lock (SELECT ... FOR UPDATE) would be
# released by the first of those commits, reopening the window
# between the clone commit and the retire commit. A session lock
# survives the inner commits and dies with its connection, so a
# crashed request can never strand it. The second request waits,
# then runs its check against the first request's COMMITTED
# result and gets the ordinary refusal. On non-Postgres engines
# (the SQLite test suite) the guard is a no-op: those engines
# serialize writers anyway, and the sequential checks still pin
# the rules there.
_TARGET_LOCK_NAMESPACE = 20261026


@contextmanager
def _target_guard(db: Session, kind: str, target_id: uuid.UUID):
    bind = db.get_bind()
    engine = getattr(bind, "engine", bind)  # a Connection unwraps to its engine
    if engine is None or engine.dialect.name != "postgresql":
        yield
        return
    key = zlib.crc32(f"claims-target:{kind}:{target_id}".encode()) - 2**31
    conn = engine.connect()
    try:
        conn.execute(
            text("SELECT pg_advisory_lock(:ns, :key)"),
            {"ns": _TARGET_LOCK_NAMESPACE, "key": key},
        )
        conn.commit()
        yield
    finally:
        try:
            conn.execute(
                text("SELECT pg_advisory_unlock(:ns, :key)"),
                {"ns": _TARGET_LOCK_NAMESPACE, "key": key},
            )
            conn.commit()
        except Exception:
            # The connection is closing either way, which releases
            # the lock; a failed unlock must never mask the result.
            pass
        finally:
            conn.close()


def _dealer_for_target(
    db: Session, owner_id: uuid.UUID, target_kind: str, record, *, personal: bool = False
) -> tuple[uuid.UUID | None, str]:
    """The dealer a warranty target answers to: its own dealer
    tag; a piece answers to its parent set's tag. `personal`
    (2026-11-05) resolves the owner's own name for the dealer —
    for OWNER-facing prefill only. The claim-create path leaves
    it off on purpose: the name it returns is snapshotted onto
    the shared claim row, and a private rename must never leak
    into a record the agent also reads."""
    company_id = getattr(record, "dealer_company_id", None)
    if target_kind == "piece":
        parent = inventory_service.get_tool(db, owner_id, record.set_id)
        company_id = parent.dealer_company_id if parent is not None else None
    if company_id is None:
        return None, ""
    names = _dealer_names(db, [company_id], owner_id if personal else None)
    return company_id, names.get(company_id, "")


def _warranty_line_pricing(
    db: Session,
    owner: core_models.User,
    *,
    target_kind: str,
    record,
    include_addons: bool,
) -> tuple[str, object]:
    """(value_basis, amount) for a warranty line. A warranty
    claim must never fail to be BORN because a price is missing —
    it prices what it can (a piece prices from its own recorded
    price, the Sets-lane figure; an asset or set from its
    PURCHASE cost — claim money is what the owner paid, owner
    ruling 2026-11-06) and otherwise starts unpriced (basis
    "entered", amount NULL — the figure is worked out with the
    dealer, not invented at the broken moment). An item with a
    replacement cost but no purchase price recorded starts
    unpriced too: the ruling's figure is the purchase cost, and
    the replacement figure never silently stands in for it."""
    if target_kind == "piece":
        price = getattr(record, "price", None)
        return "entered", (_money(price) if price is not None else None)
    try:
        amount = _line_amount(
            db,
            owner,
            target_kind=target_kind,
            record=record,
            include_addons=include_addons,
            value_basis="purchase",
            entered_amount=None,
        )
        return "purchase", amount
    except ClaimsError:
        return "entered", None


def create_warranty_claim(
    db: Session,
    owner: core_models.User,
    *,
    target_kind: str,
    target_id: uuid.UUID,
    include_addons: bool = False,
    dealer_notified: bool,
    problem: str = "",
    agent_user_id: uuid.UUID | None = None,
    private_agent_id: uuid.UUID | None = None,
    no_agent: bool = False,
    filed_with: str | None = None,
) -> tuple[models.Claim, dict]:
    """Public entry: the whole create runs under the per-target
    race guard (B-02), so the one-open-claim check inside is
    atomic against parallel creates for the same target — tool,
    battery, set or set piece alike (the piece path is the same
    call: the shared ClaimForm on the item page posts here)."""
    with _target_guard(db, target_kind, target_id):
        return _create_warranty_claim(
            db,
            owner,
            target_kind=target_kind,
            target_id=target_id,
            include_addons=include_addons,
            dealer_notified=dealer_notified,
            problem=problem,
            agent_user_id=agent_user_id,
            private_agent_id=private_agent_id,
            no_agent=no_agent,
            filed_with=filed_with,
        )


def _create_warranty_claim(
    db: Session,
    owner: core_models.User,
    *,
    target_kind: str,
    target_id: uuid.UUID,
    include_addons: bool = False,
    dealer_notified: bool,
    problem: str = "",
    agent_user_id: uuid.UUID | None = None,
    private_agent_id: uuid.UUID | None = None,
    no_agent: bool = False,
    filed_with: str | None = None,
) -> tuple[models.Claim, dict]:
    """The broken-item flow's claim: created in ONE step for an
    item (tool | battery | set) or a single set PIECE, born live
    on the warranty ladder — never a draft.

    AGENT (2026-10-31): the claim runs through the owner's agent
    for the item's dealer — by default the agent ON RECORD (the
    earliest preferred-agent row); the caller may name a
    different recorded agent, or no agent at all (no_agent), in
    which case the claim is the owner's alone and there is no
    report step — he tells the dealer himself, or doesn't.

    Reporting (Ryan's model): the caller answers "have they been
    notified yet?" — about the AGENT when the claim has one:
      - YES -> the claim starts at REPORTED (the owner told
        them); an agent whose seat is live still gets the on-site
        notice that the claim exists in the system.
      - NO -> the system tries to report it itself, TO THE AGENT:
        their site inbox when the agent link is verified, else
        the agent's email on record (a private record's address,
        or a platform agent's public contact email). Any channel
        landing starts the claim at REPORTED with
        report_method="system" and writes the contact into the
        claim's log. No agent, or no channel -> the claim starts
        at NOT_REPORTED and the owner drives it by hand. The
        dealer COMPANY is never emailed and never notified —
        it is not a party to the claim.

    FILED-WITH (overhaul, 2026-11-06): the caller may instead
    name the filing ROUTE outright (filed_with — it wins over
    the legacy no_agent flag when both arrive):
      - "agent" — the flow above, exactly.
      - "self" — the no-agent flow above, exactly.
      - "corporate" — the claim is filed straight with the
        dealer COMPANY, bypassing the agent: no agent pointer,
        and the company's VERIFIED reps become the counterparty
        seat. Reporting mirrors the agent shape with the reps as
        the channel: YES -> REPORTED (the owner told the
        company), and the reps still get the on-site notice the
        claim exists; NO -> the system reports it to the reps'
        inboxes when any exist (REPORTED, method "system", the
        contact written into the log), else NOT_REPORTED and the
        owner tells the company himself. The company is never
        EMAILED — its only channel is its reps' inboxes, and a
        claim needs a dealer on record to be filed this way at
        all (there is no company to file with otherwise).

    Returns (claim, report) where report = {"reported": bool,
    "via": ["email"|"notice", ...]}.
    """
    record = _resolve_target(db, owner.id, target_kind, target_id)
    if record is None:
        raise ClaimsNotFound("That item isn't in your vault.")
    if target_kind == "tool" and record.is_set:
        raise ClaimsError(
            f"{record.name} is a set — claim it as a set so you can "
            "choose whether its addons are included, or claim one "
            "of its pieces."
        )
    if target_kind == "set" and not record.is_set:
        raise ClaimsError(f"{record.name} isn't a set.")
    # One open warranty claim per target (the dealer-warranty
    # rule): a second live claim for the same break helps nobody.
    # Race-safe: create_warranty_claim runs this under the
    # per-target guard, so a parallel create for the same target
    # only reaches this check after this claim has committed —
    # and then reads it here and refuses with this same shape.
    open_claims = db.scalars(
        select(models.Claim)
        .join(models.ClaimLine, models.ClaimLine.claim_id == models.Claim.id)
        .where(
            models.Claim.owner_id == owner.id,
            models.Claim.kind == models.KIND_WARRANTY,
            models.Claim.status.in_(models.WARRANTY_OPEN_STATUSES),
            # A claim closed from an open status keeps that
            # status under the closed layer (2026-11-06) — it is
            # DONE, and it must not block the item's next claim.
            models.Claim.closed_at.is_(None),
            models.ClaimLine.target_kind == target_kind,
            models.ClaimLine.target_id == target_id,
        )
    ).first()
    if open_claims is not None:
        raise ClaimsError(
            f"{record.name} already has an open warranty claim "
            f"({open_claims.claim_number}) — one at a time, so the "
            "dealer isn't told twice about the same break."
        )

    company_id, dealer_name = _dealer_for_target(
        db, owner.id, target_kind, record
    )
    # The filing route (overhaul, 2026-11-06): an explicit
    # filed_with wins; the legacy no_agent flag still reads as
    # the self route for callers that predate the routes.
    mode = filed_with or (
        models.FILED_WITH_SELF if no_agent else models.FILED_WITH_AGENT
    )
    if mode not in models.FILED_WITH_MODES:
        raise ClaimsError(
            "A claim is filed one of three ways: with your agent, "
            "by yourself, or straight with the dealer (corporate)."
        )
    if mode == models.FILED_WITH_CORPORATE:
        if agent_user_id is not None or private_agent_id is not None:
            raise ClaimsError(
                "Pick one route: straight with the dealer, or "
                "through an agent — not both."
            )
        if company_id is None:
            raise ClaimsError(
                "This item has no dealer on record, so there's no "
                "dealer to file with directly — the claim stays "
                "yours to handle."
            )
        claim_agent = (None, None)
    elif mode == models.FILED_WITH_SELF:
        if agent_user_id is not None or private_agent_id is not None:
            raise ClaimsError(
                "Pick one: an agent for this claim, or no agent — not both."
            )
        claim_agent = (None, None)
    # The claim's agent (2026-10-31): the explicit pick when one
    # was made (validated against the owner's agents on record
    # for this dealer), else the default — the agent on record
    # for the dealer. (An explicit filed_with="agent" has already
    # won over a stray no_agent flag above, so the flag is not
    # consulted again here.)
    elif agent_user_id is not None or private_agent_id is not None:
        claim_agent = _validate_agent_choice(
            db, owner.id, company_id, agent_user_id, private_agent_id
        )
    else:
        claim_agent = agent_on_record(db, owner.id, company_id) or (None, None)
    if mode == models.FILED_WITH_AGENT and claim_agent == (None, None):
        # The agent route with nobody on record lands with no
        # agent at all — the honest record of that claim is the
        # self route. It keeps one rule everywhere (a claim is
        # agent-filed exactly when it carries an agent), the same
        # rule migration 0079's backfill applied to history.
        mode = models.FILED_WITH_SELF
    claim = None
    for _attempt in range(10):
        number, year, seq = _next_number(db, owner.id, models.KIND_WARRANTY)
        claim = models.Claim(
            owner_id=owner.id,
            claim_number=number,
            claim_year=year,
            number_seq=seq,
            kind=models.KIND_WARRANTY,
            incident_type="damage",
            incident_date=date.today(),
            description=(problem or "").strip(),
            status=models.STATUS_NOT_REPORTED,
            dealer_company_id=company_id,
            dealer_name=dealer_name,
            agent_user_id=claim_agent[0],
            private_agent_id=claim_agent[1],
            filed_with=mode,
        )
        db.add(claim)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            claim = None
            continue
    if claim is None:
        raise ClaimsError(
            "Couldn't assign a claim number after several tries — please retry."
        )
    basis, amount = _warranty_line_pricing(
        db,
        owner,
        target_kind=target_kind,
        record=record,
        include_addons=bool(include_addons) if target_kind == "set" else False,
    )
    _insert_line(
        db,
        owner,
        claim,
        target_kind=target_kind,
        target_id=target_id,
        record=record,
        include_addons=bool(include_addons) if target_kind == "set" else False,
        value_basis=basis,
        line_amount=amount,
    )
    # The merged pipeline (2026-11-04): a warranty claim IS the
    # item's repair, so an in-service item the claim opens on
    # reads BROKEN from this moment — the claim and the break are
    # one fact, never two records drifting apart. An item already
    # marked broken keeps its standing and its problem text (the
    # owner marked it first; the claim joins it). Other standings
    # (lost/stolen/sold/replaced) outrank the repair and are left
    # exactly as they are.
    if target_kind == "piece":
        if record.repair_state == inventory_models.STANDING_IN_SERVICE:
            record.repair_state = inventory_models.STANDING_BROKEN
            record.repair_problem = (problem or "").strip()
    elif getattr(record, "standing", None) == inventory_models.STANDING_IN_SERVICE:
        inventory_service.apply_standing(
            record, inventory_models.STANDING_BROKEN
        )
        record.repair_problem = (problem or "").strip()
    db.commit()
    db.refresh(claim)

    # -- reporting -------------------------------------------------
    # The report goes to the claim's AGENT (2026-10-31) — never
    # to the dealer company. The agent's live inbox seat is one
    # channel; the agent's email on record is the other, used
    # when the seat isn't live. No agent = no report step at all.
    agent_view = claim_agent_view(db, claim)
    agent_name = agent_view["name"] if agent_view else ""
    agent_live = agent_has_access(db, claim)
    contact_name = agent_name or dealer_name
    # How the claimed thing reads in the notices below: a piece
    # names itself, its set, and both numbers (Ryan 2026-10-25).
    item_label = record.name
    if target_kind == "piece":
        claim_lines_now = _lines(db, claim.id)
        if claim_lines_now:
            item_label = _line_display_name(claim_lines_now[0])
    if mode == models.FILED_WITH_CORPORATE:
        # -- corporate reporting (overhaul, 2026-11-06) ---------
        # The report goes to the COMPANY's verified reps — their
        # inboxes are the company's only channel (the company is
        # never emailed). The shape mirrors the agent report:
        # told-them -> REPORTED by the user, the reps still hear
        # the claim exists; not told -> the system reports it to
        # the reps when any exist, else the claim starts at
        # NOT_REPORTED and the owner tells the company himself.
        reps = corporate_party_user_ids(db, claim)
        via: list[str] = []
        if dealer_notified:
            claim.status = models.STATUS_REPORTED
            claim.reported_at = _now()
            claim.report_method = "user"
            db.add(
                models.ClaimCommunication(
                    owner_id=owner.id,
                    claim_id=claim.id,
                    channel="other",
                    contact=dealer_name,
                    summary=(
                        f"{dealer_name} was already notified before "
                        "this claim was started here."
                        if dealer_name
                        else "The dealer was already notified before "
                        "this claim was started here."
                    ),
                    occurred_at=_now(),
                    author_id=owner.id,
                    author_role="owner",
                    author_name=owner.name,
                )
            )
            db.commit()
            if reps:
                via.append("notice")
                _notify_warranty_activity(
                    db,
                    claim,
                    owner.id,
                    kind=inbox.KIND_WARRANTY_CLAIM_NEW,
                    title=f"Warranty claim {claim.claim_number}",
                    body=(
                        f"{owner.name} started a warranty claim for "
                        f"{item_label} directly with {dealer_name}."
                    ),
                )
        elif reps:
            via.append("notice")
            _notify_warranty_activity(
                db,
                claim,
                owner.id,
                kind=inbox.KIND_WARRANTY_CLAIM_NEW,
                title=f"Warranty claim {claim.claim_number}",
                body=(
                    f"{owner.name} reported a warranty claim for "
                    f"{item_label} directly with {dealer_name}."
                ),
            )
            claim.status = models.STATUS_REPORTED
            claim.reported_at = _now()
            claim.report_method = "system"
            db.add(
                models.ClaimCommunication(
                    owner_id=owner.id,
                    claim_id=claim.id,
                    channel="portal",
                    contact=dealer_name,
                    summary=(
                        "Toolbox Vault reported this warranty claim "
                        f"to {dealer_name or 'the dealer'}."
                    ),
                    occurred_at=_now(),
                    author_id=owner.id,
                    author_role="owner",
                    author_name=owner.name,
                )
            )
            db.commit()
        db.refresh(claim)
        return claim, {
            "reported": claim.status == models.STATUS_REPORTED,
            "via": via,
        }
    via: list[str] = []
    if dealer_notified:
        claim.status = models.STATUS_REPORTED
        claim.reported_at = _now()
        claim.report_method = "user"
        db.add(
            models.ClaimCommunication(
                owner_id=owner.id,
                claim_id=claim.id,
                channel="other",
                contact=contact_name,
                summary=(
                    f"{contact_name} was already notified before "
                    "this claim was started here."
                    if contact_name
                    else "The dealer was already notified before "
                    "this claim was started here."
                ),
                occurred_at=_now(),
                author_id=owner.id,
                author_role="owner",
                author_name=owner.name,
            )
        )
        db.commit()
        if agent_live:
            via.append("notice")
            _notify_warranty_activity(
                db,
                claim,
                owner.id,
                kind=inbox.KIND_WARRANTY_CLAIM_NEW,
                title=f"Warranty claim {claim.claim_number}",
                body=(
                    f"{owner.name} started a warranty claim for "
                    f"{item_label} with {dealer_name}."
                ),
            )
    else:
        emailed = False
        if agent_live:
            via.append("notice")
            _notify_warranty_activity(
                db,
                claim,
                owner.id,
                kind=inbox.KIND_WARRANTY_CLAIM_NEW,
                title=f"Warranty claim {claim.claim_number}",
                body=(
                    f"{owner.name} reported a warranty claim for "
                    f"{item_label} with {dealer_name}."
                ),
            )
        elif agent_view is not None and (agent_view["email"] or "").strip():
            emailed = _send_warranty_report_email(
                db,
                owner,
                claim,
                recipient=agent_view["email"],
                record=record,
                target_kind=target_kind,
            )
            if emailed:
                via.append("email")
        if via:
            claim.status = models.STATUS_REPORTED
            claim.reported_at = _now()
            claim.report_method = "system"
            db.add(
                models.ClaimCommunication(
                    owner_id=owner.id,
                    claim_id=claim.id,
                    channel="email" if emailed else "portal",
                    contact=contact_name,
                    summary=(
                        "Toolbox Vault reported this warranty claim "
                        f"to {contact_name or 'the dealer'}."
                    ),
                    occurred_at=_now(),
                    author_id=owner.id,
                    author_role="owner",
                    author_name=owner.name,
                )
            )
            db.commit()
    db.refresh(claim)
    return claim, {
        "reported": claim.status == models.STATUS_REPORTED,
        "via": via,
    }


def _send_warranty_report_email(
    db: Session,
    owner: core_models.User,
    claim: models.Claim,
    *,
    recipient: str,
    record,
    target_kind: str,
) -> bool:
    """The automatic report to the claim's AGENT, through the
    site's mail seam (recorded in the outbox like every real
    send). Plain facts only: what broke, whose it is, how to
    reach them, and the claim number to quote. The dealer
    company is never the recipient (2026-10-31) — the agent is
    the counterparty; the dealer's name rides as context."""
    from app.core import notifications as mail

    brand = getattr(record, "brand", "") or ""
    model = getattr(record, "model", "") or ""
    serials = getattr(record, "serial_number", "") or ""
    lines = [
        f"Warranty claim {claim.claim_number} — {claim.dealer_name}",
        "",
        f"Customer: {owner.name} ({owner.email})",
        f"Item: {record.name}",
    ]
    if target_kind == "piece":
        lines.append(f"Set piece of: {claim_line_set_name(db, claim)}")
        piece_line = next(
            (ln for ln in _lines(db, claim.id) if ln.target_kind == "piece"),
            None,
        )
        if piece_line is not None:
            if piece_line.target_part_number:
                lines.append(
                    f"Piece part number: {piece_line.target_part_number}"
                )
            if piece_line.set_model_number:
                lines.append(
                    f"Set model number: {piece_line.set_model_number}"
                )
    if brand or model:
        lines.append(f"Brand / model: {' '.join(p for p in (brand, model) if p)}")
    if serials:
        lines.append(f"Serial: {serials}")
    if claim.description:
        lines += ["", f"What happened: {claim.description}"]
    lines += [
        "",
        "This claim was reported automatically by Toolbox Vault "
        f"because you are {owner.name}'s dealer agent on record "
        f"for {claim.dealer_name or 'their dealer'}. Sign in to "
        "Toolbox Vault to see the claim and respond, or contact "
        "the customer directly.",
    ]
    return mail.send_email(
        db,
        recipient,
        subject=f"Warranty claim {claim.claim_number}: {record.name}",
        body="\n".join(lines),
        kind="warranty_claim_report",
    )


def claim_line_set_name(db: Session, claim: models.Claim) -> str:
    lines = _lines(db, claim.id)
    return lines[0].set_name if lines else ""


def list_incoming_claims(
    db: Session, user: core_models.User
) -> list[dict]:
    """The counterparty side's worklist (2026-10-31; corporate
    seat added 2026-11-06): warranty claims currently addressed
    to this user —

    - as the assigned AGENT: routed to them directly, or to a
      private agent record the owner linked to their account,
      with a live verified link (agent_has_access); or
    - as a CORPORATE rep: claims filed straight with a company
      this user holds a VERIFIED representation of
      (filed_with="corporate" — and only those: agent- and
      self-filed claims for the same company never appear).

    Nothing else appears here: not claims routed to other agents
    of the same companies, not claims whose owners merely prefer
    this user for a dealer (routing is per claim now). Each row
    carries the claim's summary plus the customer's name — the
    viewer is looking at work addressed to them, not browsing
    anyone's vault."""
    from app.modules.dealers import models as dealer_models

    from sqlalchemy import or_

    addressed_to_me = [models.Claim.agent_user_id == user.id]
    linked_private_ids = list(
        db.scalars(
            select(dealer_models.PrivateAgent.id).where(
                dealer_models.PrivateAgent.linked_user_id == user.id
            )
        )
    )
    if linked_private_ids:
        addressed_to_me.append(
            models.Claim.private_agent_id.in_(linked_private_ids)
        )
    my_companies = list(
        db.scalars(
            select(dealer_models.CompanyRepresentation.company_id).where(
                dealer_models.CompanyRepresentation.agent_user_id == user.id,
                dealer_models.CompanyRepresentation.verified.is_(True),
            )
        )
    )
    if my_companies:
        addressed_to_me.append(
            and_(
                models.Claim.filed_with == models.FILED_WITH_CORPORATE,
                models.Claim.dealer_company_id.in_(my_companies),
            )
        )
    claims = list(
        db.scalars(
            select(models.Claim)
            .where(
                models.Claim.kind == models.KIND_WARRANTY,
                models.Claim.archived.is_(False),
                models.Claim.owner_id != user.id,
                or_(*addressed_to_me),
            )
            .order_by(models.Claim.created_at.desc(), models.Claim.id.desc())
        )
    )
    # Current work first, then closed — the query ordered both
    # newest-first and this sort is stable, so groups keep it. A
    # warranty claim's "done" here is its closed layer (a
    # Repaired claim is still the counterparty's live work until
    # the owner closes it).
    claims.sort(
        key=lambda c: (
            c.closed_at is not None
            if c.kind == models.KIND_WARRANTY
            else models.is_terminal(c)
        )
    )
    rows = []
    for claim in claims:
        if claim.filed_with == models.FILED_WITH_CORPORATE:
            # The query already gated on a verified rep of THIS
            # claim's company; re-check against the live seat so
            # the rule lives in exactly one place.
            if user.id not in corporate_party_user_ids(db, claim):
                continue
        elif not agent_has_access(db, claim):
            continue  # an unverified link lists nothing (H-1)
        owner = db.get(core_models.User, claim.owner_id)
        summary = claim_summary(
            db, claim, owner_currency=owner.currency if owner is not None else None
        )
        summary["owner_name"] = owner.name if owner is not None else ""
        rows.append(summary)
    return rows


def _retire_item_for_replace(
    db: Session,
    owner: core_models.User,
    item_kind: str,
    record,
    replaced_by_item_id: uuid.UUID | None = None,
) -> None:
    """The replaced item leaves the owner's active world: the
    "replaced" standing (billing's active set and every
    sold-style exclusion treat it as gone), and any live
    marketplace listing made from it ends — a retired item is
    not for sale. The record itself is untouched history:
    reports, claims and the item's own page still read it. When
    the replacement already exists (the exact-same flow), the
    item's own REPLACED marker (asset history, 2026-10-20) is
    stamped in the same write, so the timeline shows the swap
    and what took its place."""
    from app.modules.inventory import models as inv_models
    from app.modules.marketplace import service as marketplace_service

    inventory_service.apply_standing(record, inv_models.STANDING_REPLACED)
    if replaced_by_item_id is not None:
        record.replaced_on = date.today()
        record.replaced_by_item_id = replaced_by_item_id
    marketplace_service.end_listings_for_source(
        db, owner.id, item_kind, record.id
    )
    db.commit()


def replace_item(
    db: Session,
    owner: core_models.User,
    *,
    item_kind: str,
    item_id: uuid.UUID,
    mode: str,
    amount_spent=None,
) -> dict:
    """Public entry: the whole replace runs under the per-target
    race guard (B-03), so the already-replaced check inside is
    atomic against parallel replaces of the same item."""
    with _target_guard(db, item_kind, item_id):
        return _replace_item(
            db,
            owner,
            item_kind=item_kind,
            item_id=item_id,
            mode=mode,
            amount_spent=amount_spent,
        )


def _replace_item(
    db: Session,
    owner: core_models.User,
    *,
    item_kind: str,
    item_id: uuid.UUID,
    mode: str,
    amount_spent=None,
) -> dict:
    """The broken prompt's Replace path.

    mode "same" (the exact same item, Ryan's $15 case): a NEW
    item is created carrying ALL the old item's data except its
    purchase price (= what the user spent) and purchase date
    (= today); the acquisition ledger records the new purchase
    through inventory's own create path, exactly like a fresh
    entry. mode "different" (an upgrade): no new item here —
    the old one retires and the caller sends the user to the
    normal add flow.

    Either way the old item retires to the "replaced" standing.
    An item on an OPEN claim (either kind) refuses — the claim
    owns it until it closes, the delete-guard rule."""
    if item_kind == "tool":
        record = inventory_service.get_tool(db, owner.id, item_id)
    elif item_kind == "battery":
        record = inventory_service.get_battery(db, owner.id, item_id)
    else:
        raise ClaimsError("Replacements target a tool or a battery.")
    if record is None:
        raise ClaimsNotFound("That item isn't in your vault.")
    # Already replaced (B-03): a replaced item is retired history —
    # replacing it again would clone a clone and retire the same
    # record twice. Checked here, inside the per-target guard, so
    # parallel replaces can't both pass: the loser re-reads the
    # standing the winner's retire committed and refuses.
    from app.modules.inventory import models as _inv_models

    if getattr(record, "standing", None) == _inv_models.STANDING_REPLACED:
        raise ClaimsError(
            "This item has already been replaced — it can't be "
            "replaced again."
        )
    # The claim check, with replace-specific copy first, then the
    # full delete-guard as a backstop (attached addons, set
    # pieces — the shapes a plain target check can't see).
    found = _open_line(
        db,
        owner.id,
        target_kinds=("battery",) if item_kind == "battery" else ("tool", "set"),
        target_id=item_id,
    )
    if found is None and item_kind == "tool":
        piece_hit = db.execute(
            select(models.ClaimLine, models.Claim)
            .join(models.Claim, models.ClaimLine.claim_id == models.Claim.id)
            .where(
                models.Claim.owner_id == owner.id,
                models.Claim.status.in_(models.ALL_OPEN_STATUSES),
                models.ClaimLine.target_kind == "piece",
                models.ClaimLine.set_id == item_id,
            )
        ).first()
        if piece_hit:
            found = piece_hit
    if found is not None:
        _, open_claim = found
        raise ClaimsError(
            f"This item is on open claim {open_claim.claim_number} — "
            "close the claim before replacing it."
        )
    guard = delete_guard(db, owner.id, item_kind, item_id)
    if guard:
        raise ClaimsError(guard)

    new_item = None
    if mode == "same":
        new_item = _clone_item_for_replace(
            db, owner, item_kind, record, amount_spent
        )
    elif mode != "different":
        raise ClaimsError("Choose the same item or a different one.")
    _retire_item_for_replace(
        db,
        owner,
        item_kind,
        record,
        replaced_by_item_id=new_item.id if new_item is not None else None,
    )
    return {
        "retired_id": record.id,
        "new_item": (
            {"kind": item_kind, "id": new_item.id, "name": new_item.name}
            if new_item is not None
            else None
        ),
    }


def _clone_item_for_replace(
    db: Session,
    owner: core_models.User,
    item_kind: str,
    record,
    amount_spent,
):
    """Build the replacement through inventory's OWN create path
    (validation, location write, dealer check, tag sync, the
    acquisition ledger — all the fresh-entry machinery), with
    every field copied from the old record except price + date.
    Attachments ride along by reference: the new record lists
    the same stored files (they were never the old record's to
    lose). Set pieces copy as fresh rows — identity, prices and
    their files — starting back in service."""
    from app.modules.inventory import models as inv_models
    from app.modules.inventory import schemas as inv_schemas

    today = date.today()
    id_column = (
        inv_models.ItemTag.tool_id
        if item_kind == "tool"
        else inv_models.ItemTag.battery_id
    )
    tag_ids = [
        row.tag_id
        for row in db.scalars(
            select(inv_models.ItemTag).where(
                inv_models.ItemTag.item_kind == item_kind,
                id_column == record.id,
            )
        )
    ]
    if item_kind == "tool":
        pieces_payload = None
        old_pieces: list = []
        if record.is_set:
            old_pieces = inventory_service._list_set_pieces(db, record.id)
            pieces_payload = [
                {
                    "kind": p.kind,
                    "name": p.name,
                    "part_number": p.part_number,
                    "serial_number": p.serial_number,
                    "status": p.status,
                    "price": p.price,
                    "purchase_date": p.purchase_date,
                    "sort_order": p.sort_order,
                }
                for p in old_pieces
            ]
        payload = inv_schemas.ToolCreate(
            name=record.name,
            brand=record.brand,
            model=record.model,
            serial_number=record.serial_number,
            condition=record.condition,
            category=record.category,
            location=record.location,
            location_id=record.location_id,
            notes=record.notes,
            purchase_price=amount_spent,
            purchase_date=today,
            replacement_cost=record.replacement_cost,
            msrp=record.msrp,
            warranty_months=record.warranty_months,
            warranty_provider=record.warranty_provider,
            warranty_contact=record.warranty_contact,
            warranty_terms=record.warranty_terms,
            warranty_type=record.warranty_type,
            quantity=record.quantity,
            size=record.size,
            model_numbers=list(record.model_numbers or []) or None,
            serial_numbers=list(record.serial_numbers or []) or None,
            upc=record.upc,
            consumable=record.consumable,
            business_use=record.business_use,
            rebuy_store=record.rebuy_store,
            rebuy_url=record.rebuy_url,
            rebuy_sku=record.rebuy_sku,
            rebuy_notes=record.rebuy_notes,
            is_set=record.is_set,
            dealer_company_id=record.dealer_company_id,
            tag_ids=tag_ids,
            custom_data=dict(record.custom_data or {}),
            pieces=pieces_payload,
        )
        new = inventory_service.create_tool(db, owner.id, payload)
        if old_pieces:
            new_pieces = inventory_service._list_set_pieces(db, new.id)
            for old_piece, new_piece in zip(old_pieces, new_pieces):
                new_piece.attachments = [
                    dict(a) for a in (old_piece.attachments or [])
                ]
        if record.attached_to_set_id is not None:
            new.attached_to_set_id = record.attached_to_set_id
    else:
        payload = inv_schemas.BatteryCreate(
            name=record.name,
            brand=record.brand,
            model=record.model,
            serial_number=record.serial_number,
            condition=record.condition,
            category=record.category,
            business_use=record.business_use,
            location=record.location,
            location_id=record.location_id,
            notes=record.notes,
            purchase_price=amount_spent,
            purchase_date=today,
            replacement_cost=record.replacement_cost,
            msrp=record.msrp,
            platform=record.platform,
            voltage=record.voltage,
            capacity_ah=record.capacity_ah,
            chemistry=record.chemistry,
            warranty_months=record.warranty_months,
            warranty_provider=record.warranty_provider,
            warranty_contact=record.warranty_contact,
            warranty_terms=record.warranty_terms,
            warranty_type=record.warranty_type,
            quantity=record.quantity,
            upc=record.upc,
            dealer_company_id=record.dealer_company_id,
            tag_ids=tag_ids,
            custom_data=dict(record.custom_data or {}),
        )
        new = inventory_service.create_battery(db, owner.id, payload)
    new.attachments = [dict(a) for a in (record.attachments or [])]
    db.commit()
    db.refresh(new)
    return new


# -- wizard targets ---------------------------------------------------------------


def list_targets(db: Session, owner: core_models.User) -> dict:
    """The wizard's target picker + evidence source data: the
    owner's assets (top-level tools incl. sets with their pieces,
    and batteries) projected from inventory's serializers — values
    a line can price from, and the attachments evidence can
    reference."""
    tools = []
    for tool in inventory_service.list_tools(db, owner.id):
        view = inventory_service.serialize_tool(db, tool)
        entry = {
            "kind": "set" if tool.is_set else "tool",
            "id": view["id"],
            "name": view["name"],
            "brand": view["brand"],
            "model": view["model"],
            "serial_number": view["serial_number"],
            "quantity": view["quantity"],
            "purchase_price": view["purchase_price"],
            "replacement_cost": view["replacement_cost"],
            "msrp": view["msrp"],
            "attachments": view["attachments"],
            "pieces": [],
        }
        if tool.is_set and view.get("set"):
            for piece in (
                view["set"]["core_pieces"] + view["set"]["addon_pieces"]
            ):
                entry["pieces"].append(
                    {
                        "id": piece["id"],
                        "name": piece["name"],
                        "kind": piece["kind"],
                        "part_number": piece["part_number"],
                        "serial_number": piece["serial_number"],
                        "status": piece["status"],
                        "attachments": piece["attachments"],
                    }
                )
        tools.append(entry)
    batteries = []
    for battery in inventory_service.list_batteries(db, owner.id):
        view = inventory_service.serialize_battery(db, battery)
        batteries.append(
            {
                "kind": "battery",
                "id": view["id"],
                "name": view["name"],
                "brand": view["brand"],
                "model": view["model"],
                "serial_number": view["serial_number"],
                "quantity": view["quantity"],
                "purchase_price": view["purchase_price"],
                "replacement_cost": view["replacement_cost"],
                "msrp": view["msrp"],
                "attachments": view["attachments"],
                "pieces": [],
            }
        )
    return {"tools": tools, "batteries": batteries}


# -- stats -------------------------------------------------------------------------


def stats(db: Session, owner_id: uuid.UUID, kind: str) -> dict:
    """One section's home stat (claims separation, 2026-11-05):
    that kind's claims still in flight for the owner — insurance
    drafts included (models.HOME_STATUSES; deep audit F1-23: the
    section's page presents drafts as live work, so its count
    derives from that same population); warranty claims count
    across their open ladder. Only terminal claims (per kind)
    and archived ones drop out. Each section's widget reads its
    own stat — the two numbers never blend."""
    if kind == models.KIND_WARRANTY:
        # The Repair claims population (overhaul, 2026-11-06):
        # the 7 open statuses — Repaired is finished work, not
        # open — not closed (the closed layer shelves a claim
        # from any status), not archived.
        count = db.scalar(
            select(func.count(models.Claim.id)).where(
                models.Claim.owner_id == uuid.UUID(str(owner_id)),
                models.Claim.kind == kind,
                models.Claim.status.in_(models.WARRANTY_OPEN_STATUSES),
                models.Claim.closed_at.is_(None),
                models.Claim.archived.is_(False),
            )
        )
        return {"open_claims_count": int(count or 0)}
    count = db.scalar(
        select(func.count(models.Claim.id)).where(
            models.Claim.owner_id == uuid.UUID(str(owner_id)),
            models.Claim.kind == kind,
            models.Claim.status.in_(models.HOME_STATUSES),
            models.Claim.archived.is_(False),
        )
    )
    return {"open_claims_count": int(count or 0)}


# -- billing lapse pin (the A1 seam, wired) ------------------------------------------


def _open_claim_condition():
    """The SQL truth for "this claim is OPEN" — the population
    the billing pin and the inventory delete guards protect.
    Insurance: its open statuses (filed / in review / approved —
    drafts pin nothing). Warranty (overhaul, 2026-11-06): in
    flight = any status but Repaired, and NOT closed — a claim
    closed from an open status keeps that status under the
    closed layer, so the status list alone would keep pinning a
    finished claim's items forever."""
    return or_(
        and_(
            models.Claim.kind == models.KIND_INSURANCE,
            models.Claim.status.in_(models.OPEN_STATUSES),
        ),
        and_(
            models.Claim.kind == models.KIND_WARRANTY,
            models.Claim.status.in_(models.WARRANTY_OPEN_STATUSES),
            models.Claim.closed_at.is_(None),
        ),
    )


def pinned_asset_ids(
    db: Session, owner_id: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Billing pin provider (registered into the entitlement
    engine at import): the (tool ids, battery ids) targeted by
    this owner's OPEN claims. Set lines pin the set's own record
    (the asset that holds a plan slot); piece lines pin their
    PARENT SET for the same reason — the piece is not an asset,
    the set is. Drafts pin nothing; paid/denied/closed claims
    have released their items."""
    tools: set[uuid.UUID] = set()
    batteries: set[uuid.UUID] = set()
    rows = db.execute(
        select(
            models.ClaimLine.target_kind,
            models.ClaimLine.target_id,
            models.ClaimLine.set_id,
        )
        .join(models.Claim, models.ClaimLine.claim_id == models.Claim.id)
        .where(
            models.Claim.owner_id == uuid.UUID(str(owner_id)),
            _open_claim_condition(),
        )
    ).all()
    for target_kind, target_id, set_id in rows:
        if target_kind == "battery":
            batteries.add(target_id)
        elif target_kind == "piece":
            if set_id is not None:
                tools.add(set_id)
        else:  # tool | set — the tool record itself
            tools.add(target_id)
    return tools, batteries


# -- inventory delete guard ------------------------------------------------------------


def _open_line(
    db: Session,
    owner_id: uuid.UUID,
    *,
    target_kinds: tuple[str, ...],
    target_id: uuid.UUID,
) -> tuple[models.ClaimLine, models.Claim] | None:
    row = db.execute(
        select(models.ClaimLine, models.Claim)
        .join(models.Claim, models.ClaimLine.claim_id == models.Claim.id)
        .where(
            models.Claim.owner_id == owner_id,
            _open_claim_condition(),
            models.ClaimLine.target_kind.in_(target_kinds),
            models.ClaimLine.target_id == target_id,
        )
    ).first()
    return (row[0], row[1]) if row else None


def _open_set_line(
    db: Session, owner_id: uuid.UUID, set_id: uuid.UUID
) -> tuple[models.ClaimLine, models.Claim] | None:
    return _open_line(db, owner_id, target_kinds=("set",), target_id=set_id)


def delete_guard(
    db: Session, owner_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> str | None:
    """Inventory delete-guard registry entry (registered at
    import): refuse to pull an item out from under an OPEN claim.

    kind "tool" — the tool record itself (a set IS a tool record),
        plus an attached addon tool whose set is claimed with
        addons included.
    kind "battery" — a targeted battery.
    kind "piece" — a targeted piece, or any piece of a set with an
        open set line (removing it takes the claimed set apart).
    kind "detach" — a tool leaving a set: refused when the tool
        itself is claimed or the set it leaves is claimed.

    Returns the refusal copy (naming the claim) or None to allow.
    """
    if kind == "battery":
        found = _open_line(db, owner_id, target_kinds=("battery",), target_id=item_id)
        if found:
            _, claim = found
            return (
                f"This battery is on open claim {claim.claim_number} — "
                "close the claim before deleting it."
            )
        return None
    if kind == "piece":
        found = _open_line(db, owner_id, target_kinds=("piece",), target_id=item_id)
        if found:
            _, claim = found
            return (
                f"This piece is on open claim {claim.claim_number} — "
                "close the claim before removing it."
            )
        piece = inventory_service.get_set_piece(db, owner_id, item_id)
        if piece is not None:
            found = _open_set_line(db, owner_id, piece.set_id)
            if found:
                _, claim = found
                return (
                    f"This piece belongs to a set on open claim "
                    f"{claim.claim_number} — close the claim before "
                    "taking the set apart."
                )
        return None
    # tool + detach share the direct-target check.
    found = _open_line(
        db, owner_id, target_kinds=("tool", "set"), target_id=item_id
    )
    if found:
        _, claim = found
        if kind == "detach":
            return (
                f"This item is on open claim {claim.claim_number} — "
                "close the claim before detaching it."
            )
        return (
            f"This item is on open claim {claim.claim_number} — "
            "close the claim before deleting it."
        )
    if kind == "tool":
        # Deleting a set deletes its pieces with it — a piece of
        # this set on an open claim blocks the whole deletion.
        piece_line = db.execute(
            select(models.ClaimLine, models.Claim)
            .join(models.Claim, models.ClaimLine.claim_id == models.Claim.id)
            .where(
                models.Claim.owner_id == owner_id,
                _open_claim_condition(),
                models.ClaimLine.target_kind == "piece",
                models.ClaimLine.set_id == item_id,
            )
        ).first()
        if piece_line:
            _, claim = piece_line
            return (
                f"A piece of this set is on open claim {claim.claim_number} — "
                "close the claim before deleting the set."
            )
    tool = inventory_service.get_tool(db, owner_id, item_id)
    if tool is not None and tool.attached_to_set_id is not None:
        found = _open_set_line(db, owner_id, tool.attached_to_set_id)
        if found:
            line, claim = found
            # An attached tool only rides the claim when the owner
            # included addons; otherwise the claim doesn't cover it.
            if kind == "detach" or line.include_addons:
                return (
                    f"This item rides inside a set on open claim "
                    f"{claim.claim_number} — close the claim before "
                    "taking the set apart."
                )
    return None


# -- jobs seam --------------------------------------------------------------------------


def _add_months(moment: datetime, months: int) -> datetime:
    """Calendar months later (the backorder cadence is monthly,
    in Ryan's words — not every 30 days): same day-of-month,
    clamped to the target month's last day."""
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return moment.replace(year=year, month=month, day=day)


def run_backorder_reminders(
    db: Session, now: datetime | None = None
) -> int:
    """The monthly backorder check-in (owner order, 2026-11-05
    #8): while a WARRANTY claim sits in the Backordered status,
    its owner and its seated counterparty (the verified agent on
    an agent-filed claim, the company's verified reps on a
    corporate-filed claim, nobody extra on a self-filed claim)
    get ONE inbox reminder a month to check for backorder
    updates — the first a month after the claim entered the
    status, monthly thereafter while it stays.

    The clock lives on the claim (backorder_entered_at /
    backorder_last_reminded_at, migration 0079): a claim is due
    when a month has passed since it entered or was last
    reminded, whichever is later, and stamping last-reminded in
    the same commit as the notifications makes a job re-run
    inside the month a no-op (dedupe by construction, like the
    readiness nudge). Leaving the status — or closing the claim,
    or shelving it — stops future reminders without any cleanup:
    the query only ever picks up claims that are backordered
    right now. Returns how many claims were reminded."""
    now = now or _now()
    claims = db.scalars(
        select(models.Claim).where(
            models.Claim.kind == models.KIND_WARRANTY,
            models.Claim.status == models.STATUS_BACKORDERED,
            models.Claim.closed_at.is_(None),
            models.Claim.archived.is_(False),
            models.Claim.backorder_entered_at.is_not(None),
        )
    ).all()
    reminded = 0
    for claim in claims:
        base = claim.backorder_last_reminded_at or claim.backorder_entered_at
        if base is None:
            continue
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)  # SQLite reads back naive
        if _add_months(base, 1) > now:
            continue
        lines = _lines(db, claim.id)
        item_name = _line_display_name(lines[0]) if lines else "an item"
        recipients = {claim.owner_id} | claim_counterparty_user_ids(db, claim)
        for uid in recipients:
            inbox.create_notification(
                db,
                uid,
                kind=inbox.KIND_CLAIM_BACKORDER,
                title=f"Backorder check-in — claim {claim.claim_number}",
                body=(
                    f"The {item_name} on claim {claim.claim_number} has "
                    "been marked Backordered for a month — time to check "
                    "whether there's an update on it."
                ),
                data={
                    "claim_id": str(claim.id),
                    "claim_number": claim.claim_number,
                },
                commit=False,
            )
        claim.backorder_last_reminded_at = now
        reminded += 1
    db.commit()
    return reminded


def run_deadline_notifications(db: Session, today: date | None = None) -> int:
    """Notify owners about claim deadlines that are due within
    DEADLINE_WARNING_DAYS (or already overdue) — ONE notification
    per (claim, deadline): re-runs create nothing, and if a
    deadline is MOVED to a new date the new date earns its own
    notification. Returns how many were created.

    - proof of loss: open claims (filed / in review / approved)
      that haven't marked it sent yet;
    - recoverable depreciation: approved / paid claims.

    The dedupe key lives in the notification's data payload
    (claim_id + deadline field + due date), the maintenance jobs
    pattern — identical on Postgres and SQLite."""
    today = today or date.today()
    horizon = today + timedelta(days=DEADLINE_WARNING_DAYS)
    existing = db.scalars(
        select(core_models.Notification).where(
            core_models.Notification.kind == inbox.KIND_CLAIM_DEADLINE
        )
    )
    seen = {
        (
            str(n.user_id),
            (n.data or {}).get("claim_id"),
            (n.data or {}).get("deadline"),
            (n.data or {}).get("due_date"),
        )
        for n in existing
    }
    created = 0
    # Deadlines are the DISASTER section's machinery (proof of
    # loss, recoverable depreciation — insurance concepts only;
    # claims separation, 2026-11-05): the job reads insurance
    # claims and nothing else.
    claims = db.scalars(
        select(models.Claim).where(
            models.Claim.kind == models.KIND_INSURANCE
        )
    )
    for claim in claims:
        checks: list[tuple[str, str, date]] = []
        if (
            claim.status in OPEN_STATUSES
            and claim.proof_of_loss_due is not None
            and claim.proof_of_loss_sent_at is None
            and claim.proof_of_loss_due <= horizon
        ):
            checks.append(
                ("proof_of_loss", "Proof of loss", claim.proof_of_loss_due)
            )
        if (
            claim.status in (models.STATUS_APPROVED, models.STATUS_PAID)
            and claim.depreciation_deadline is not None
            and claim.depreciation_deadline <= horizon
        ):
            checks.append(
                (
                    "depreciation",
                    "Recoverable depreciation",
                    claim.depreciation_deadline,
                )
            )
        for field, label, due in checks:
            key = (str(claim.owner_id), str(claim.id), field, due.isoformat())
            if key in seen:
                continue
            seen.add(key)
            when = (
                f"was due {due.isoformat()}"
                if due < today
                else f"is due {due.isoformat()}"
            )
            inbox.create_notification(
                db,
                claim.owner_id,
                kind=inbox.KIND_CLAIM_DEADLINE,
                title=f"{label} deadline — {claim.claim_number}",
                body=(
                    f"{label} for claim {claim.claim_number} {when}. "
                    "Open the claim to review its checklist."
                ),
                data={
                    "claim_id": str(claim.id),
                    "claim_number": claim.claim_number,
                    "deadline": field,
                    "due_date": due.isoformat(),
                },
                commit=False,
            )
            created += 1
    if created:
        db.commit()
    return created


# -- export ------------------------------------------------------------------------------


def export_rows(
    db: Session, owner_id: uuid.UUID, kind: str | None = None
) -> dict:
    """The data export's claims picture: every claim of ONE kind
    (claims separation, 2026-11-05 — the export writes claims.json
    for warranty and disaster_claims.json for insurance) with its
    snapshotted lines, its evidence (uploads carry their stored
    dict; core's export walks those files into the archive) and
    its communications log."""
    stmt = (
        select(models.Claim)
        .where(models.Claim.owner_id == uuid.UUID(str(owner_id)))
        .order_by(models.Claim.created_at)
    )
    if kind is not None:
        stmt = stmt.where(models.Claim.kind == kind)
    claims = db.scalars(stmt)
    payload = []
    for claim in claims:
        lines = _lines(db, claim.id)
        evidence = []
        for row in _evidence_rows(db, claim.id):
            evidence.append(
                {
                    "id": row.id,
                    "source": row.source,
                    "item_kind": row.item_kind,
                    "item_id": row.item_id,
                    "attachment_key": row.attachment_key,
                    "filename": row.filename,
                    "kind": row.kind,
                    "attachment": row.attachment,
                    "created_at": row.created_at,
                }
            )
        payload.append(
            {
                "id": claim.id,
                "claim_number": claim.claim_number,
                "kind": claim.kind,
                "dealer_company_id": claim.dealer_company_id,
                "dealer_name": claim.dealer_name,
                "agent_user_id": claim.agent_user_id,
                "private_agent_id": claim.private_agent_id,
                "manufacturer_case_number": claim.manufacturer_case_number,
                "reported_at": claim.reported_at,
                "report_method": claim.report_method,
                "repair_sent_to": claim.repair_sent_to,
                "repair_cost": claim.repair_cost,
                "repair_completed_at": claim.repair_completed_at,
                "insurer_name": claim.insurer_name,
                "policy_number": claim.policy_number,
                "agent_name": claim.agent_name,
                "agent_phone": claim.agent_phone,
                "agent_email": claim.agent_email,
                "incident_type": claim.incident_type,
                "incident_date": claim.incident_date,
                "description": claim.description,
                "status": claim.status,
                "police_report_number": claim.police_report_number,
                "police_department": claim.police_department,
                "police_report_date": claim.police_report_date,
                "proof_of_loss_due": claim.proof_of_loss_due,
                "proof_of_loss_sent_at": claim.proof_of_loss_sent_at,
                "depreciation_deadline": claim.depreciation_deadline,
                "filed_at": claim.filed_at,
                "closed_at": claim.closed_at,
                "created_at": claim.created_at,
                "updated_at": claim.updated_at,
                "lines": [line_view(r) for r in lines],
                "evidence": evidence,
                "communications": [
                    comm_view(r) for r in _comm_rows(db, claim.id)
                ],
            }
        )
    return {"claims": payload}


def repair_cost_rows(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """Reports seam (repairs ∪ claims merge, 2026-11-04): every
    warranty claim of the owner's carrying a recorded repair
    cost, in the row shape the old maintenance repair views fed
    the reports (item_name / problem / status / sent_to /
    repair_cost / reported_at / completed_at) — the repair-costs
    report and the year-end ledger read claims now, because the
    claim IS the repair record. Dated by repair completion,
    falling back to the claim's own timestamps."""
    claims = db.scalars(
        select(models.Claim)
        .where(
            models.Claim.owner_id == uuid.UUID(str(owner_id)),
            models.Claim.kind == models.KIND_WARRANTY,
            models.Claim.repair_cost.is_not(None),
        )
        .order_by(models.Claim.created_at)
    )
    rows = []
    for claim in claims:
        lines = _lines(db, claim.id)
        rows.append(
            {
                "id": claim.id,
                "item_name": (
                    _line_display_name(lines[0]) if lines else ""
                ),
                "problem": claim.description,
                "status": claim.status,
                "sent_to": claim.repair_sent_to,
                "repair_cost": claim.repair_cost,
                "reported_at": claim.reported_at or claim.created_at,
                "completed_at": claim.repair_completed_at,
            }
        )
    return rows


# -- asset history provider (registered into inventory's feed) -----------------

# Claim statuses worth a line in an item's life story.
_MILESTONE_STATUSES = (
    models.STATUS_APPROVED,
    models.STATUS_DENIED,
    models.STATUS_PAID,
    models.STATUS_CLOSED,
    # Warranty milestones: the dealer was told, the item went
    # out for repair, the work is done (the merged repair
    # pipeline's beats, 2026-11-04).
    models.STATUS_REPORTED,
    models.STATUS_IN_REPAIR,
    models.STATUS_COMPLETED,
)


def _milestone_detail(
    db: Session, owner_id: uuid.UUID, claim: models.Claim, status: str
) -> str:
    """The repair facts riding a warranty milestone (merge,
    2026-11-04): where the item went, and — when the work
    completed — what it cost. This is the repair history the
    retired repair records used to tell, now told by the claim
    itself on the item's Audit tab."""
    if claim.kind != models.KIND_WARRANTY:
        return ""
    parts = []
    if status in (models.STATUS_IN_REPAIR, models.STATUS_COMPLETED):
        if claim.repair_sent_to:
            parts.append(f"Sent to {claim.repair_sent_to}")
    if status == models.STATUS_COMPLETED and claim.repair_cost is not None:
        cost = inventory_history.money(
            claim.repair_cost, inventory_history.owner_currency(db, owner_id)
        )
        if cost:
            parts.append(f"Cost {cost}")
    return " · ".join(parts)


def history_events(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> list[inventory_history.HistoryEvent]:
    """Asset-history provider: claims whose lines target this
    item — the filing, plus the status milestones (approved /
    denied / paid / closed). A piece line lands on its parent
    SET's page (the set is the asset); the piece's name rides in
    the detail. Milestone timestamps come from the claim's
    change-journal transitions; a claim whose transitions
    predate the journal falls back to its own timestamps."""
    if item_kind == "tool":
        line_match = (
            (
                (models.ClaimLine.target_kind == "tool")
                & (models.ClaimLine.target_id == item_id)
            )
            | (
                (models.ClaimLine.target_kind == "set")
                & (models.ClaimLine.target_id == item_id)
            )
            | (
                (models.ClaimLine.target_kind == "piece")
                & (models.ClaimLine.set_id == item_id)
            )
        )
    else:
        line_match = (models.ClaimLine.target_kind == "battery") & (
            models.ClaimLine.target_id == item_id
        )
    lines = list(
        db.scalars(
            select(models.ClaimLine).where(
                models.ClaimLine.owner_id == owner_id, line_match
            )
        )
    )
    if not lines:
        return []
    piece_names: dict[uuid.UUID, str] = {}
    claim_ids: list[uuid.UUID] = []
    for line in lines:
        if line.claim_id not in claim_ids:
            claim_ids.append(line.claim_id)
        if line.target_kind == "piece" and line.target_name:
            piece_names.setdefault(line.claim_id, line.target_name)
    claims = [
        claim
        for claim in (db.get(models.Claim, cid) for cid in claim_ids)
        if claim is not None and claim.owner_id == owner_id
    ]
    events: list[inventory_history.HistoryEvent] = []
    for claim in claims:
        # Each event links into ITS OWN section (claims
        # separation, 2026-11-05): warranty claims live under
        # /claims, disaster claims under /disaster-claims.
        link = (
            f"/claims/{claim.id}"
            if claim.kind == models.KIND_WARRANTY
            else f"/disaster-claims/{claim.id}"
        )
        detail_parts = []
        if claim.kind == models.KIND_WARRANTY:
            detail_parts.append("Warranty")
            if claim.dealer_name:
                detail_parts.append(claim.dealer_name)
        elif claim.incident_type:
            detail_parts.append(claim.incident_type.capitalize())
        if claim.insurer_name:
            detail_parts.append(claim.insurer_name)
        if claim.id in piece_names:
            detail_parts.append(f"Piece: {piece_names[claim.id]}")
        filed_ts = claim.filed_at or (
            claim.created_at if claim.status != models.STATUS_DRAFT else None
        )
        if filed_ts is not None:
            events.append(
                inventory_history.HistoryEvent(
                    ts=filed_ts,
                    kind="claim",
                    title=f"Claim {claim.claim_number} filed",
                    detail=" · ".join(detail_parts),
                    link=link,
                )
            )
        # Milestones from the journal's status transitions (the
        # claim rows carry no transition log of their own).
        transitions = db.scalars(
            select(core_models.ChangeJournal).where(
                core_models.ChangeJournal.user_id == owner_id,
                core_models.ChangeJournal.entity_type == "claim",
                core_models.ChangeJournal.entity_id == claim.id,
                core_models.ChangeJournal.action == "update",
            )
        )
        seen_statuses: set[str] = set()
        for entry in transitions:
            before_status = (entry.before or {}).get("status")
            after_status = (entry.after or {}).get("status")
            if (
                after_status in _MILESTONE_STATUSES
                and after_status != before_status
            ):
                seen_statuses.add(after_status)
                events.append(
                    inventory_history.HistoryEvent(
                        ts=entry.occurred_at,
                        kind="claim",
                        title=f"Claim {claim.claim_number} {after_status}",
                        detail=_milestone_detail(db, owner_id, claim, after_status),
                        link=link,
                    )
                )
        if claim.status in _MILESTONE_STATUSES and claim.status not in seen_statuses:
            # No journaled transition (legacy claim): one
            # milestone at the best timestamp the row carries.
            ts = (
                claim.closed_at
                if claim.status == models.STATUS_CLOSED and claim.closed_at
                else claim.updated_at
            )
            events.append(
                inventory_history.HistoryEvent(
                    ts=ts,
                    kind="claim",
                    title=f"Claim {claim.claim_number} {claim.status}",
                    detail=_milestone_detail(db, owner_id, claim, claim.status),
                    link=link,
                )
            )
    return events


# -- cross-module wiring (import time, one direction only) ---------------------
#
# Billing's lapse pin (the seam left in entitlements._active_asset_ids
# by Phase A1) and inventory's delete guards both work through
# provider registries: claims registers, the engines consult, and
# neither engine imports this module. Registration is idempotent
# in both registries, so re-imports are harmless.

entitlements.register_pin_provider(pinned_asset_ids)
inventory_service.register_delete_guard(delete_guard)
inventory_history.register_history_provider("claims", history_events)
