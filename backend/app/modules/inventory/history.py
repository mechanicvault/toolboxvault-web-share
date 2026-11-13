"""Asset history timeline (owner spec 2026-10-20): every asset
shows its life story — purchased, warranty repaired, lent,
claimed, lost, replaced — as ONE chronological feed on its
detail page.

Read-side by construction. The timeline is not a table: each
module that owns a slice of an item's life registers a PROVIDER
here, and the feed merges whatever the registered providers
yield for the item. The registry is the whole connection (the
billing pin-provider pattern): this module never imports a
provider's module, so removing a module removes its events
with it, and an item with no provider modules behaves exactly
as before they existed.

A provider is a callable:

    provider(db, owner_id, item_kind, item_id) -> Iterable[HistoryEvent]

with item_kind "tool" | "battery" (a set is a tool). Providers
yield events in their own natural order; item_history merges,
normalizes timestamps to aware UTC, and sorts newest first.

WAVE 2 (sold tracking): register sale events with ONE line in
the marketplace/sales service at import time, exactly like the
claims pin registration:

    inventory_history.register_history_provider("marketplace", history_events)

No change is needed in this file or in the routes — the new
events appear in the feed the moment the provider module is
imported.
"""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import models as core_models
from app.modules.inventory import models


@dataclass
class HistoryEvent:
    """One line of an item's life story. `ts` is when it
    happened (date-only facts — purchase date, service dates —
    ride at midnight UTC and the UI renders them date-only).
    `link` is an in-app path the title can point at (the
    replacement item, the claim), or None."""

    ts: datetime
    kind: str
    title: str
    detail: str = ""
    link: str | None = None


# Event kinds (the frontend maps each to an icon):
#   created, purchased, edited, standing, replaced, repair,
#   service, lent, returned, claim, lost, recovered, warranty

HistoryProvider = Callable[
    [Session, uuid.UUID, str, uuid.UUID], Iterable[HistoryEvent]
]

_providers: list[tuple[str, HistoryProvider]] = []


def register_history_provider(module_name: str, provider: HistoryProvider) -> None:
    """Register an item-history provider. Idempotent by identity,
    so a module re-import never double-registers."""
    if all(existing is not provider for _name, existing in _providers):
        _providers.append((module_name, provider))


def unregister_history_provider(provider: HistoryProvider) -> None:
    """Remove a provider (test seam — production code never
    unregisters; removing a module removes its import)."""
    _providers[:] = [
        (name, existing) for name, existing in _providers if existing is not provider
    ]


def registered_providers() -> list[str]:
    return [name for name, _provider in _providers]


# -- helpers -------------------------------------------------------------------


def aware(value: datetime | None) -> datetime | None:
    """Normalize a stored timestamp to aware UTC. Postgres
    returns aware values; SQLite (tests) returns naive ones —
    the feed must compare them against each other and against
    date-derived midnights without crashing."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def money(value: Decimal | None, currency: str = "USD") -> str:
    """History-feed money text — the ONE formatter (wave 3), in
    the item OWNER's currency (the feed is the owner's own
    surface). None renders empty (the event simply omits it)."""
    if value is None:
        return ""
    from app.modules.core import money as core_money

    return core_money.format_money(value, currency)


def owner_currency(db: Session, owner_id: uuid.UUID) -> str:
    """The currency history events for this owner's items render
    in (their account's — v1 semantics)."""
    from app.modules.core import models as core_models
    from app.modules.core import money as core_money

    user = db.get(core_models.User, owner_id)
    return core_money.normalize_currency(user.currency if user else "USD")


def item_ref(
    db: Session, owner_id: uuid.UUID, item_id: uuid.UUID
) -> tuple[str, str, str] | None:
    """(kind, name, in-app link) for one of the owner's items,
    whichever table holds it — the replacement marker's id may
    name a tool or a battery. None when the item is gone (the
    marker outlives the replacement record by design)."""
    tool = db.get(models.Tool, item_id)
    if tool is not None and tool.owner_id == owner_id:
        return "tool", tool.name, f"/inventory/{tool.id}"
    battery = db.get(models.Battery, item_id)
    if battery is not None and battery.owner_id == owner_id:
        return "battery", battery.name, f"/inventory/batteries/{battery.id}"
    return None


# -- the feed --------------------------------------------------------------------


def item_history(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> list[dict]:
    """Every registered provider's events for one item, merged
    and sorted newest first, in the wire shape. The caller (the
    route) has already proven the item is the owner's — a
    foreign id never reaches here."""
    events: list[HistoryEvent] = []
    for _name, provider in list(_providers):
        for event in provider(db, owner_id, item_kind, item_id):
            ts = aware(event.ts)
            if ts is None:
                continue
            events.append(
                HistoryEvent(
                    ts=ts,
                    kind=event.kind,
                    title=event.title,
                    detail=event.detail,
                    link=event.link,
                )
            )
    # Newest first; the sort is stable, so same-timestamp events
    # keep provider order (registration order: inventory first).
    events.sort(key=lambda e: e.ts, reverse=True)
    return [
        {
            "ts": event.ts,
            "kind": event.kind,
            "title": event.title,
            "detail": event.detail,
            "link": event.link,
        }
        for event in events
    ]


# -- inventory's own provider -----------------------------------------------------
#
# What inventory itself knows: the record's birth, its purchase
# date, the replaced marker (both directions), the lost/stolen
# report records, and the item's own change-journal milestones.


_NOISE_FIELDS = {
    # Mirror/owned-elsewhere fields: their stories are told by
    # the owning providers (maintenance, dealers, this module's
    # replaced + loss events), never twice.
    "repair_state",
    "repair_problem",
    "replaced_on",
    "replaced_by_item_id",
    "replaced_note",
    # Location text/paths resync in bulk when a tree node is
    # renamed — a cascade artifact, not an edit to the item.
    "location",
    "location_id",
}

_STANDING_TITLES = {
    "broken": "Marked broken",
    "in_repair": "Marked in repair",
    "lost": "Marked lost",
    "stolen": "Marked stolen",
    "in_service": "Back in service",
}


def _attachment_keys(rows: object) -> list[str]:
    if not isinstance(rows, list):
        return []
    return sorted(
        str(row.get("key", "")) for row in rows if isinstance(row, dict)
    )


def _repair_timestamps(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> tuple[list[datetime], list[datetime]]:
    """(started_at, completed_at) of the item's warranty claims —
    the coverage check that keeps a journal standing change from
    double-telling a break the claims provider already tells.
    Since the repairs ∪ claims merge (2026-11-04) the claim IS
    the repair record: its creation is the break moment, its
    repair_completed_at the fix. Lazy import: claims owns the
    records; inventory reads them only for this dedupe, and
    inventory must import standalone even where claims is absent.
    Piece claims land on their parent set, like their lines."""
    try:
        from app.modules.claims import models as claim_models
    except ImportError:
        return [], []
    if item_kind == "tool":
        line_match = (
            (
                (claim_models.ClaimLine.target_kind == "tool")
                & (claim_models.ClaimLine.target_id == item_id)
            )
            | (
                (claim_models.ClaimLine.target_kind == "set")
                & (claim_models.ClaimLine.target_id == item_id)
            )
            | (
                (claim_models.ClaimLine.target_kind == "piece")
                & (claim_models.ClaimLine.set_id == item_id)
            )
        )
    else:
        line_match = (claim_models.ClaimLine.target_kind == "battery") & (
            claim_models.ClaimLine.target_id == item_id
        )
    stmt = (
        select(claim_models.Claim.created_at, claim_models.Claim.repair_completed_at)
        .join(
            claim_models.ClaimLine,
            claim_models.ClaimLine.claim_id == claim_models.Claim.id,
        )
        .where(
            claim_models.Claim.owner_id == owner_id,
            claim_models.Claim.kind == claim_models.KIND_WARRANTY,
            line_match,
        )
    )
    reported: list[datetime] = []
    completed: list[datetime] = []
    for created_at, completed_at in db.execute(stmt):
        if created_at is not None:
            reported.append(aware(created_at))
        if completed_at is not None:
            completed.append(aware(completed_at))
    return reported, completed


def _near(stamps: list[datetime], moment: datetime, days: int = 2) -> bool:
    window = timedelta(days=days)
    return any(abs(stamp - moment) <= window for stamp in stamps)


def _journal_events(
    db: Session,
    owner_id: uuid.UUID,
    item_kind: str,
    item_id: uuid.UUID,
    loss_reports: list[models.ItemLossReport],
) -> list[HistoryEvent]:
    """The item's own journal milestones: entry labels for real
    edits, standing transitions for standing changes no module
    record covers (a bulk-edit mark with no repair/loss record
    still lands in the story — once)."""
    entries = list(
        db.scalars(
            select(core_models.ChangeJournal)
            .where(
                core_models.ChangeJournal.user_id == owner_id,
                core_models.ChangeJournal.entity_type == item_kind,
                core_models.ChangeJournal.entity_id == item_id,
                core_models.ChangeJournal.action == "update",
            )
            .order_by(core_models.ChangeJournal.seq.asc())
        )
    )
    if not entries:
        return []
    reported, completed = _repair_timestamps(db, owner_id, item_kind, item_id)
    report_created = [
        aware(r.created_at) for r in loss_reports if r.created_at is not None
    ]
    report_recovered = [
        aware(r.updated_at)
        for r in loss_reports
        if r.status == "recovered" and r.updated_at is not None
    ]
    events: list[HistoryEvent] = []
    for entry in entries:
        before = entry.before or {}
        after = entry.after or {}
        occurred = aware(entry.occurred_at)
        changed = {
            key
            for key in set(before) | set(after)
            if before.get(key) != after.get(key)
        } - {"updated_at"}
        if "attachments" in changed:
            # A reorder (same files, new sequence) is layout
            # trivia; an added/removed file is a real edit.
            if _attachment_keys(before.get("attachments")) == _attachment_keys(
                after.get("attachments")
            ):
                changed.discard("attachments")
        standing_change = None
        if "standing" in changed:
            standing_change = (before.get("standing"), after.get("standing"))
            changed.discard("standing")
        changed -= _NOISE_FIELDS
        if changed:
            events.append(
                HistoryEvent(
                    ts=occurred,
                    kind="edited",
                    title=entry.label,
                )
            )
        if standing_change is not None:
            old, new = standing_change
            if new == old or new is None:
                continue
            covered = False
            if new in ("lost", "stolen"):
                covered = _near(report_created, occurred)
            elif new in ("broken", "in_repair"):
                covered = _near(reported, occurred)
            elif new == "in_service" and old in ("lost", "stolen"):
                covered = _near(report_recovered, occurred)
            elif new == "in_service" and old in ("broken", "in_repair"):
                covered = _near(completed, occurred)
            if not covered:
                events.append(
                    HistoryEvent(
                        ts=occurred,
                        kind="standing",
                        title=_STANDING_TITLES.get(new, f"Marked {new}"),
                    )
                )
    return events


def _loss_events(
    rows: list[models.ItemLossReport],
) -> list[HistoryEvent]:
    events: list[HistoryEvent] = []
    for row in rows:
        detail_parts = []
        if row.police_report_number:
            detail_parts.append(f"Police report {row.police_report_number}")
        if row.police_department:
            detail_parts.append(row.police_department)
        if row.insurer_name:
            detail_parts.append(f"Insurer: {row.insurer_name}")
        if row.claim_number:
            detail_parts.append(f"Claim {row.claim_number}")
        events.append(
            HistoryEvent(
                ts=(
                    day_start(row.reported_date)
                    if row.reported_date
                    else aware(row.created_at)
                ),
                kind="lost",
                title=f"Reported {row.standing}",
                detail=" · ".join(detail_parts),
            )
        )
        if row.status == "recovered":
            events.append(
                HistoryEvent(
                    ts=(
                        day_start(row.recovered_date)
                        if row.recovered_date
                        else aware(row.updated_at)
                    ),
                    kind="recovered",
                    title="Recovered",
                )
            )
    return events


def _replaced_events(
    db: Session,
    owner_id: uuid.UUID,
    item_kind: str,
    item_id: uuid.UUID,
    record,
) -> list[HistoryEvent]:
    events: list[HistoryEvent] = []
    if record.replaced_on is not None:
        title = "Replaced"
        link = None
        if record.replaced_by_item_id is not None:
            ref = item_ref(db, owner_id, record.replaced_by_item_id)
            if ref is not None:
                _kind, name, link = ref
                title = f"Replaced by {name}"
        events.append(
            HistoryEvent(
                ts=day_start(record.replaced_on),
                kind="replaced",
                title=title,
                detail=record.replaced_note or "",
                link=link,
            )
        )
    # Reverse: items whose marker names THIS item as their
    # replacement — the new record's story opens with what it
    # replaced. Plain-column match on both tables.
    for model in (models.Tool, models.Battery):
        predecessors = db.scalars(
            select(model).where(
                model.owner_id == owner_id,
                model.replaced_by_item_id == item_id,
            )
        )
        for old in predecessors:
            if old.id == item_id:
                continue
            old_kind = "tool" if model is models.Tool else "battery"
            link = (
                f"/inventory/{old.id}"
                if old_kind == "tool"
                else f"/inventory/batteries/{old.id}"
            )
            events.append(
                HistoryEvent(
                    ts=(
                        day_start(old.replaced_on)
                        if old.replaced_on
                        else aware(old.updated_at)
                    ),
                    kind="replaced",
                    title=f"Replaced {old.name}",
                    detail=old.replaced_note or "",
                    link=link,
                )
            )
    return events


def inventory_history_events(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> list[HistoryEvent]:
    record = None
    if item_kind == "tool":
        record = db.get(models.Tool, item_id)
    elif item_kind == "battery":
        record = db.get(models.Battery, item_id)
    if record is None or record.owner_id != owner_id:
        return []
    events: list[HistoryEvent] = [
        HistoryEvent(
            ts=aware(record.created_at),
            kind="created",
            title="Added to inventory",
        )
    ]
    if record.purchase_date is not None:
        price = money(record.purchase_price, owner_currency(db, owner_id))
        events.append(
            HistoryEvent(
                ts=day_start(record.purchase_date),
                kind="purchased",
                title="Purchased",
                detail=f"Purchase price {price}" if price else "",
            )
        )
    loss_reports = list(
        db.scalars(
            select(models.ItemLossReport).where(
                models.ItemLossReport.owner_id == owner_id,
                models.ItemLossReport.item_kind == item_kind,
                models.ItemLossReport.item_id == item_id,
            )
        )
    )
    events.extend(_loss_events(loss_reports))
    events.extend(_replaced_events(db, owner_id, item_kind, item_id, record))
    events.extend(_journal_events(db, owner_id, item_kind, item_id, loss_reports))
    return events


register_history_provider("inventory", inventory_history_events)
