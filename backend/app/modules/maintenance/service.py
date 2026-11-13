"""Maintenance service: schedules and upkeep (repairs moved out).

SERVICE INTERFACE (stable; bump manifest version on change):
  - item_standing(db, owner, item_kind, item_id) -> dict
        (the detail-page picture: standing, schedules; sets add
        per-piece standings)
  - create_schedule / update_schedule / delete_schedule / log_done
  - overview(db, owner) -> dict   (module page: out-of-service
        board + every schedule with its computed due standing)
  - stats(db, owner_id) -> dict   (the two home stats)
  - run_overdue_notifications(db, today=None) -> int
        (the jobs seam: one inbox notification per schedule per
        due date when it slips overdue; idempotent on re-runs)
  - export_rows(db, owner_id) -> dict   (the data export's
        maintenance.json — schedules only since the merge)

REPAIRS ∪ CLAIMS MERGE (2026-11-04, migration 0074): this module
used to own the repair lifecycle (repair_records: one row per
break->fix cycle). Ryan's ruling — "the thought process behind a
repair is the same thing as a warranty claim" — folded repairs
into the claims module: the warranty claim carries the working
end (sent-to, repair cost, completion), drives the item's
standing, and tells the repair story on the item's Audit tab.
The old records were converted to claims by the migration; the
lifecycle functions (mark_broken / send_for_repair /
update_record / mark_fixed) are retired with the table. What
remains here is the standing READER side: the out-of-service
board reads standing off the inventory records and the repair
facts (problem, since) off the item's open warranty claim.

A checked-out item CAN be marked broken (it happens in the
field) — borrowing's hand-back flow owns the lend; borrowing
refuses to START a lend on a broken/in-repair item by reading
the standing off the inventory record, no import of this module
needed.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.inventory import history as inventory_history
from app.modules.inventory import service as inventory_service
from app.modules.maintenance import models

ITEM_KINDS = models.ITEM_KINDS
SCHEDULE_ITEM_KINDS = ("tool", "battery")

# A schedule due within this window (or past due) is "due".
DUE_SOON_DAYS = 7

_GONE_PIECE_STATUSES = ("sold", "removed")


class MaintenanceError(ValueError):
    """Caller turns this into a 4xx."""


class MaintenanceNotFound(MaintenanceError):
    """The item/record/schedule named does not exist (or is not the
    caller's — deliberately indistinguishable)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- item resolution -------------------------------------------------------


def _live_schedules(
    db: Session, rows
) -> list:
    """Schedules whose item still exists. Schedules carry no FK to
    their item (ledger style, like repair records), so deleting an
    item retires its schedules from every board/stat/job view here;
    the rows themselves go with the account-deletion cascade (and
    stay in the owner's data export — a backup keeps everything)."""
    return [
        s
        for s in rows
        if _resolve_item(db, s.owner_id, s.item_kind, s.item_id) is not None
    ]


def _resolve_item(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
):
    """The owner's inventory record for (kind, id) through
    inventory's service interface, or None. Pieces resolve to the
    SetPiece row."""
    if item_kind == "tool":
        return inventory_service.get_tool(db, owner_id, item_id)
    if item_kind == "battery":
        return inventory_service.get_battery(db, owner_id, item_id)
    if item_kind == "piece":
        return inventory_service.get_set_piece(db, owner_id, item_id)
    raise MaintenanceError("Items are tools, batteries, or set pieces.")


# -- serialization -----------------------------------------------------------


def log_view(row: models.MaintenanceLogEntry) -> dict:
    return {
        "id": row.id,
        "schedule_id": row.schedule_id,
        "done_date": row.done_date,
        "cost": row.cost,
        "technician": row.technician,
        "notes": row.notes,
        # Documents for this service event (Package B — calibration
        # certificates), serialized with fresh read URLs.
        "attachments": inventory_service.serialize_attachments(row),
        "created_at": row.created_at,
    }


def next_due(schedule: models.MaintenanceSchedule) -> date | None:
    """The computed next due date — never stored, so never stale.

    An interval schedule counts from its last logged/done date;
    before anything is done, the fixed due_date is the seed (a
    one-off schedule is just a due_date with no interval)."""
    if schedule.interval_days and schedule.last_done_at is not None:
        return schedule.last_done_at + timedelta(days=schedule.interval_days)
    if schedule.due_date is not None:
        return schedule.due_date
    return None


def due_status(schedule: models.MaintenanceSchedule, today: date | None = None) -> str:
    """overdue | due_soon (<= 7 days, today included) | ok | unknown."""
    due = next_due(schedule)
    if due is None:
        return "unknown"
    today = today or date.today()
    if due < today:
        return "overdue"
    if due <= today + timedelta(days=DUE_SOON_DAYS):
        return "due_soon"
    return "ok"


def schedule_view(
    db: Session,
    schedule: models.MaintenanceSchedule,
    *,
    item_name: str | None = None,
    today: date | None = None,
) -> dict:
    entries = db.scalars(
        select(models.MaintenanceLogEntry)
        .where(models.MaintenanceLogEntry.schedule_id == schedule.id)
        .order_by(
            models.MaintenanceLogEntry.done_date.desc(),
            models.MaintenanceLogEntry.created_at.desc(),
        )
    )
    return {
        "id": schedule.id,
        "item_kind": schedule.item_kind,
        "item_id": schedule.item_id,
        "item_name": item_name if item_name is not None else schedule.item_name,
        "kind": schedule.kind,
        "label": schedule.label,
        "interval_days": schedule.interval_days,
        "due_date": schedule.due_date,
        "last_done_at": schedule.last_done_at,
        "next_due": next_due(schedule),
        "due_status": due_status(schedule, today),
        "log": [log_view(e) for e in entries],
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


# -- schedules -----------------------------------------------------------------


def _schedule_or_404(
    db: Session, owner_id: uuid.UUID, schedule_id: uuid.UUID
) -> models.MaintenanceSchedule:
    row = db.get(models.MaintenanceSchedule, schedule_id)
    if row is None or row.owner_id != owner_id:
        raise MaintenanceNotFound("That schedule doesn't exist.")
    return row


def create_schedule(
    db: Session,
    owner: core_models.User,
    *,
    item_kind: str,
    item_id: uuid.UUID,
    kind: str,
    label: str = "",
    interval_days: int | None = None,
    due_date: date | None = None,
    last_done_at: date | None = None,
) -> models.MaintenanceSchedule:
    if item_kind not in SCHEDULE_ITEM_KINDS:
        raise MaintenanceError("Schedules belong to tools or batteries.")
    if interval_days is None and due_date is None:
        raise MaintenanceError(
            "Give the schedule an interval or a due date — otherwise it can never come due."
        )
    item = _resolve_item(db, owner.id, item_kind, item_id)
    if item is None:
        raise MaintenanceNotFound("That item isn't in your vault.")
    row = models.MaintenanceSchedule(
        owner_id=owner.id,
        item_kind=item_kind,
        item_id=item_id,
        item_name=item.name,
        kind=kind,
        label=(label or "").strip(),
        interval_days=interval_days,
        due_date=due_date,
        last_done_at=last_done_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_schedule(
    db: Session,
    owner: core_models.User,
    schedule_id: uuid.UUID,
    **changes,
) -> models.MaintenanceSchedule:
    row = _schedule_or_404(db, owner.id, schedule_id)
    # Validate the RESULT before mutating: a schedule stripped of
    # both its interval and its due date could never come due.
    new_interval = changes.get("interval_days", row.interval_days)
    new_due = changes.get("due_date", row.due_date)
    if new_interval is None and new_due is None:
        raise MaintenanceError(
            "A schedule needs an interval or a due date — otherwise it can never come due."
        )
    for key, value in changes.items():
        if key == "label" and value is not None:
            value = value.strip()
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def delete_schedule(db: Session, owner: core_models.User, schedule_id: uuid.UUID) -> bool:
    row = db.get(models.MaintenanceSchedule, schedule_id)
    if row is None or row.owner_id != owner.id:
        return False
    # Log entries are deleted EXPLICITLY (ORM), not left to the FK
    # cascade: the change journal only sees ORM deletes, and a
    # restore of the schedule must bring its history back with it
    # (audit trail, 2026-10-19). The cascade remains the backstop.
    for entry in db.scalars(
        select(models.MaintenanceLogEntry).where(
            models.MaintenanceLogEntry.schedule_id == row.id
        )
    ):
        db.delete(entry)
    db.delete(row)
    db.commit()
    return True


def log_done(
    db: Session,
    owner: core_models.User,
    schedule_id: uuid.UUID,
    *,
    done_date: date | None = None,
    cost=None,
    technician: str = "",
    notes: str = "",
) -> models.MaintenanceLogEntry:
    """Record performed work: a log row (the schedule's history)
    and the schedule's last_done_at advances to the done date —
    which is what moves its computed next due."""
    schedule = _schedule_or_404(db, owner.id, schedule_id)
    entry = models.MaintenanceLogEntry(
        owner_id=owner.id,
        schedule_id=schedule.id,
        done_date=done_date or date.today(),
        cost=cost,
        technician=(technician or "").strip(),
        notes=notes or "",
    )
    db.add(entry)
    if schedule.last_done_at is None or entry.done_date > schedule.last_done_at:
        schedule.last_done_at = entry.done_date
    db.commit()
    db.refresh(entry)
    return entry


def schedules_for_item(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> list[models.MaintenanceSchedule]:
    return list(
        db.scalars(
            select(models.MaintenanceSchedule)
            .where(
                models.MaintenanceSchedule.owner_id == owner_id,
                models.MaintenanceSchedule.item_kind == item_kind,
                models.MaintenanceSchedule.item_id == item_id,
            )
            .order_by(models.MaintenanceSchedule.created_at)
        )
    )


# -- standings / overview / stats -----------------------------------------------


def item_standing(
    db: Session, owner: core_models.User, item_kind: str, item_id: uuid.UUID
) -> dict:
    """One item's care picture for its detail page: the standing
    (read off the inventory record — the claims lifecycle writes
    it since the merge) and its schedules. For a set (a tool with
    pieces), each piece's standing rides along — the socket-set
    case: the set stays in service while one socket is out being
    repaired. Repair HISTORY no longer rides here — it lives on
    the item's claims (Claims / Replace tab + Audit tab)."""
    item = _resolve_item(db, owner.id, item_kind, item_id)
    if item is None:
        raise MaintenanceNotFound("That item isn't in your vault.")
    view = {
        "item_kind": item_kind,
        "item_id": item_id,
        "item_name": item.name,
        # The item's standing (Package B): tools/batteries read the
        # standing column — a lost tool mid-repair reads "lost"
        # here while its claim stays untouched.
        "state": getattr(item, "standing", item.repair_state),
        "problem": item.repair_problem,
        "schedules": [
            schedule_view(db, s, item_name=item.name)
            for s in schedules_for_item(db, owner.id, item_kind, item_id)
        ]
        if item_kind in SCHEDULE_ITEM_KINDS
        else [],
        "pieces": [],
    }
    if item_kind == "tool" and getattr(item, "is_set", False):
        pieces = inventory_service.resolve_set_members(db, item, True, include_gone=True)
        piece_rows = list(pieces["core_pieces"]) + list(pieces["addon_pieces"])
        view["pieces"] = [
            {
                "piece_id": piece.id,
                "name": piece.name,
                "kind": piece.kind,
                "state": piece.repair_state,
                "problem": piece.repair_problem,
            }
            for piece in piece_rows
        ]
    return view


def _open_claims_by_target(db: Session, owner_id: uuid.UUID) -> dict:
    """The owner's OPEN warranty claims keyed by (target_kind,
    target_id) — the merged pipeline's repair facts for the
    out-of-service board (merge, 2026-11-04): the problem and
    the since-date live on the claim now. The claims tables are
    read lazily (the tag doctrine: maintenance never hard-depends
    on the claims module — with claims switched off the board
    simply falls back to the standing's own problem text)."""
    try:
        from app.modules.claims import models as claim_models
    except ImportError:
        return {}
    rows = db.execute(
        select(claim_models.Claim, claim_models.ClaimLine)
        .join(
            claim_models.ClaimLine,
            claim_models.ClaimLine.claim_id == claim_models.Claim.id,
        )
        .where(
            claim_models.Claim.owner_id == owner_id,
            claim_models.Claim.kind == claim_models.KIND_WARRANTY,
            claim_models.Claim.status.in_(
                claim_models.WARRANTY_OPEN_STATUSES
            ),
            # Not closed (the closed layer, claims overhaul
            # 2026-11-06): a closed claim's facts stop riding
            # the board even though its status survives.
            claim_models.Claim.closed_at.is_(None),
        )
    ).all()
    by_target: dict = {}
    for claim, line in rows:
        by_target.setdefault((line.target_kind, line.target_id), claim)
        if line.target_kind == "set":
            by_target.setdefault(("tool", line.target_id), claim)
    return by_target


def _out_of_service(
    db: Session, owner_id: uuid.UUID, include_claim_facts: bool = True
) -> list[dict]:
    """Every item of the owner's currently out of service —
    tools, batteries, and set pieces — board order: by kind then
    name. `since` is the open claim's creation moment and the
    problem is the claim's, when a claim is driving the repair
    (the merged pipeline); claim_id/claim_number ride along so
    the board can link straight at the claim.

    `include_claim_facts=False` is the claims-module-off read
    (Repairs & Maintenance merge, 2026-11-05): the claims tables
    are never consulted, so the board falls back to the
    standing's own problem text and carries no claim link or
    status — the doctrine `_open_claims_by_target` documents,
    enforced at this seam for the merged page's board."""
    entries: list[dict] = []
    claims_by_target = (
        _open_claims_by_target(db, owner_id) if include_claim_facts else {}
    )

    def add(kind: str, record, set_id=None, set_name: str = "") -> None:
        claim = claims_by_target.get((kind, record.id))
        entries.append(
            {
                "item_kind": kind,
                "item_id": record.id,
                "item_name": record.name,
                "set_id": set_id,
                "set_name": set_name,
                "state": getattr(record, "standing", record.repair_state),
                "problem": (
                    (claim.description if claim is not None else "")
                    or record.repair_problem
                ),
                # A claimless break has no claim clock: the
                # standing write's own stamp is its since (the
                # record's updated_at — the break was the write
                # that took it out of service).
                "since": (
                    claim.created_at
                    if claim is not None
                    else getattr(record, "updated_at", None)
                ),
                "claim_id": claim.id if claim is not None else None,
                "claim_number": (
                    claim.claim_number if claim is not None else None
                ),
                "claim_status": (
                    claim.status if claim is not None else None
                ),
            }
        )

    # The board is about REPAIR standing: an item is out of service
    # when its repair_state leaves in-service — a lost-but-healthy
    # item (standing lost, repair_state in_service) does NOT board;
    # a lost item mid-repair boards with state "lost".
    for tool in inventory_service.list_tools(db, owner_id, include_attached=True):
        if tool.repair_state != models.STATE_IN_SERVICE:
            add("tool", tool)
        if tool.is_set:
            members = inventory_service.resolve_set_members(
                db, tool, True, include_gone=True
            )
            for piece in list(members["core_pieces"]) + list(members["addon_pieces"]):
                if piece.repair_state != models.STATE_IN_SERVICE:
                    add("piece", piece, set_id=tool.id, set_name=tool.name)
    for battery in inventory_service.list_batteries(db, owner_id):
        if battery.repair_state != models.STATE_IN_SERVICE:
            add("battery", battery)
    entries.sort(key=lambda e: (e["item_kind"], e["item_name"].lower()))
    return entries


def out_of_service_board(db: Session, owner: core_models.User) -> list[dict]:
    """The out-of-service board on its own (Repairs & Maintenance
    merge, 2026-11-05): on the merged page the board is the
    landing tab and rides on INVENTORY, not on this module — a
    user whose maintenance module is off keeps the board. The
    claim facts (link, number, status) ride only while the
    claims module is effective for the owner; with claims off
    the board is standings only."""
    from app.modules.core import module_control

    include_claim_facts = module_control.effective_for_user(
        db, "claims", owner.account_types, user_id=owner.id
    )
    return _out_of_service(
        db, owner.id, include_claim_facts=include_claim_facts
    )


def overview(db: Session, owner: core_models.User) -> dict:
    """The module page: the out-of-service board + every schedule
    the owner has, each with its computed due standing."""
    schedules = _live_schedules(
        db,
        db.scalars(
            select(models.MaintenanceSchedule)
            .where(models.MaintenanceSchedule.owner_id == owner.id)
            .order_by(models.MaintenanceSchedule.created_at)
        ),
    )
    return {
        "out_of_service": _out_of_service(db, owner.id),
        "schedules": [schedule_view(db, s) for s in schedules],
    }


def stats(db: Session, owner_id: uuid.UUID) -> dict:
    """The home stats. Maintenance due counts schedules whose
    computed next due is within DUE_SOON_DAYS (overdue included);
    out of service counts items (tools + batteries + pieces) whose
    standing isn't in_service."""
    today = date.today()
    horizon = today + timedelta(days=DUE_SOON_DAYS)
    due_count = 0
    for schedule in _live_schedules(
        db,
        db.scalars(
            select(models.MaintenanceSchedule).where(
                models.MaintenanceSchedule.owner_id == owner_id
            )
        ),
    ):
        due = next_due(schedule)
        if due is not None and due <= horizon:
            due_count += 1
    return {
        "maintenance_due_count": due_count,
        "out_of_service_count": len(_out_of_service(db, owner_id)),
    }


# -- jobs seam -------------------------------------------------------------------


def run_overdue_notifications(db: Session, today: date | None = None) -> int:
    """Notify owners about schedules that have slipped overdue —
    ONE notification per (schedule, due date): when the schedule is
    done and comes due again on a new date, that new date earns its
    own notification. Re-runs create nothing (the jobs-seam
    idempotency rule). Returns how many notifications were created.

    The dedupe key lives in the notification's data payload
    (schedule_id + due_date), checked in Python so the rule is
    identical on Postgres and SQLite."""
    today = today or date.today()
    created = 0
    schedules = _live_schedules(db, db.scalars(select(models.MaintenanceSchedule)))
    for schedule in schedules:
        due = next_due(schedule)
        if due is None or due >= today:
            continue
        existing = db.scalars(
            select(core_models.Notification).where(
                core_models.Notification.user_id == schedule.owner_id,
                core_models.Notification.kind == inbox.KIND_MAINTENANCE_OVERDUE,
            )
        )
        already = any(
            (n.data or {}).get("schedule_id") == str(schedule.id)
            and (n.data or {}).get("due_date") == due.isoformat()
            for n in existing
        )
        if already:
            continue
        label = schedule.label or schedule.kind
        inbox.create_notification(
            db,
            schedule.owner_id,
            kind=inbox.KIND_MAINTENANCE_OVERDUE,
            title="Maintenance overdue",
            body=(
                f"{schedule.item_name} — {label} was due "
                f"{due.isoformat()}. Log it done from the item's "
                "Maintenance section."
            ),
            data={
                "schedule_id": str(schedule.id),
                "item_kind": schedule.item_kind,
                "item_id": str(schedule.item_id),
                "item_name": schedule.item_name,
                "due_date": due.isoformat(),
            },
            commit=False,
        )
        created += 1
    if created:
        db.commit()
    return created


# -- asset history provider (registered into inventory's feed) -----------------

_SERVICE_TITLES = {
    "calibration": "Calibration done",
    "service": "Service done",
    "inspection": "Inspection done",
    "other": "Maintenance done",
}


def history_events(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> list[inventory_history.HistoryEvent]:
    """Asset-history provider: this item's schedule completions
    ("service" events). The repair story used to be told here
    from repair records — since the repairs ∪ claims merge
    (2026-11-04) the CLAIMS provider tells it (the claim is the
    repair), so this provider carries schedules only."""
    events: list[inventory_history.HistoryEvent] = []
    schedules = schedules_for_item(db, owner_id, item_kind, item_id)
    if schedules:
        by_id = {s.id: s for s in schedules}
        entries = db.scalars(
            select(models.MaintenanceLogEntry)
            .where(
                models.MaintenanceLogEntry.owner_id == owner_id,
                models.MaintenanceLogEntry.schedule_id.in_(list(by_id)),
            )
            .order_by(models.MaintenanceLogEntry.done_date)
        )
        for entry in entries:
            schedule = by_id[entry.schedule_id]
            detail_parts = []
            if schedule.label:
                detail_parts.append(schedule.label)
            if entry.technician:
                detail_parts.append(f"By {entry.technician}")
            if entry.cost is not None:
                cost = inventory_history.money(
                    entry.cost, inventory_history.owner_currency(db, owner_id)
                )
                if cost:
                    detail_parts.append(f"Cost {cost}")
            events.append(
                inventory_history.HistoryEvent(
                    ts=inventory_history.day_start(entry.done_date),
                    kind="service",
                    title=_SERVICE_TITLES.get(schedule.kind, "Service done"),
                    detail=" · ".join(detail_parts),
                )
            )
    return events


inventory_history.register_history_provider("maintenance", history_events)


# -- export ------------------------------------------------------------------------


def export_rows(db: Session, owner_id: uuid.UUID) -> dict:
    """The data export's maintenance.json: every schedule (with
    its log) the user owns. Repairs are NOT here since the merge
    (2026-11-04) — they are claims now and export with them
    (claims.json carries the repair facts)."""
    schedules = db.scalars(
        select(models.MaintenanceSchedule)
        .where(models.MaintenanceSchedule.owner_id == owner_id)
        .order_by(models.MaintenanceSchedule.created_at)
    )
    return {
        "schedules": [schedule_view(db, s) for s in schedules],
    }
