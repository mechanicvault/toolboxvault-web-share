"""Claim-readiness nudges (audit A8, 2026-10-22).

A weekly-cadence inbox nudge for owners whose ACTIVE items are
missing the records an insurer asks for first — a photo, a model
or serial number, or a purchase price. The gap computation reuses
the inventory Health Check (photo/identifier) and adds the value
check (purchase_price unset) over the same active population.

Posture, per the audit item:
  - helpful, never naggy: ONE nudge per user per period, and the
    copy points at the Health Check instead of scolding;
  - a per-user SILENCE switch (users.silence_claim_readiness_
    nudges, Settings -> Notifications) opts out for good;
  - a global operator kill switch + tunable interval live in the
    admin system settings (the same store/posture as the forum
    and marketplace switches);
  - the period stamp is the user's newest claim_readiness
    notification itself — no extra bookkeeping table, and the
    inbox history IS the audit trail.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.billing import entitlements
from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.inventory import service as inventory_service

READINESS_ENABLED_KEY = "claims.readiness_nudges_enabled"
READINESS_INTERVAL_KEY = "claims.readiness_nudge_interval_days"
DEFAULT_INTERVAL_DAYS = 7


def nudges_enabled(db: Session) -> bool:
    return bool(entitlements.get_setting(db, READINESS_ENABLED_KEY, True))


def nudge_interval_days(db: Session) -> int:
    try:
        days = int(entitlements.get_setting(db, READINESS_INTERVAL_KEY, DEFAULT_INTERVAL_DAYS))
    except (TypeError, ValueError):
        days = DEFAULT_INTERVAL_DAYS
    return max(1, days)


def readiness_gap_counts(db: Session, owner_id: uuid.UUID) -> dict[str, int]:
    """{items_with_gaps, photo, identifier, value} over the
    owner's ACTIVE items — the Health Check population and rules,
    plus the purchase-price (value) gap the Health Check doesn't
    track. The identifier gap counts items with NEITHER a model
    nor a serial number — either one alone satisfies it (owner
    ruling 2026-11-03). Zero across the board = claim-ready."""
    health = inventory_service.health_check(db, owner_id)
    photo = health["counts"].get("photo", 0)
    identifier = health["counts"].get("identifier", 0)

    active_tools = entitlements.active_tool_ids(db, owner_id)
    active_batteries = entitlements.active_battery_ids(db, owner_id)
    value = 0
    gapped_ids: set[tuple[str, uuid.UUID]] = {
        (item["kind"], item["id"]) for item in health["items"]
    }
    for tool in inventory_service.list_tools(db, owner_id):
        if active_tools is not None and tool.id not in active_tools:
            continue
        if tool.purchase_price is None:
            value += 1
            gapped_ids.add(("tool", tool.id))
    for battery in inventory_service.list_batteries(db, owner_id):
        if active_batteries is not None and battery.id not in active_batteries:
            continue
        if battery.purchase_price is None:
            value += 1
            gapped_ids.add(("battery", battery.id))
    return {
        "items_with_gaps": len(gapped_ids),
        "photo": photo,
        "identifier": identifier,
        "value": value,
    }


def _last_nudge_at(db: Session, user_id: uuid.UUID) -> datetime | None:
    return db.scalar(
        select(core_models.Notification.created_at)
        .where(
            core_models.Notification.user_id == user_id,
            core_models.Notification.kind == inbox.KIND_CLAIM_READINESS,
        )
        .order_by(core_models.Notification.created_at.desc())
        .limit(1)
    )


def run_readiness_nudges(db: Session, today: date | None = None) -> int:
    """Send this period's nudges. Returns how many were created.
    Idempotent per user per period by construction (the newest
    nudge is the stamp the next run checks)."""
    if not nudges_enabled(db):
        return 0
    today = today or datetime.now(timezone.utc).date()
    cutoff = datetime.combine(
        today - timedelta(days=nudge_interval_days(db)), time.min, tzinfo=timezone.utc
    )
    sent = 0
    users = db.scalars(
        select(core_models.User).where(core_models.User.is_active.is_(True))
    ).all()
    for user in users:
        if user.silence_claim_readiness_nudges:
            continue
        last = _last_nudge_at(db, user.id)
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)  # SQLite reads back naive
        if last is not None and last >= cutoff:
            continue
        gaps = readiness_gap_counts(db, user.id)
        if gaps["items_with_gaps"] == 0:
            continue
        missing_bits = []
        if gaps["photo"]:
            missing_bits.append(f"{gaps['photo']} without a photo")
        if gaps["identifier"]:
            missing_bits.append(
                f"{gaps['identifier']} without a model or serial number"
            )
        if gaps["value"]:
            missing_bits.append(f"{gaps['value']} without a purchase price")
        inbox.create_notification(
            db,
            user.id,
            kind=inbox.KIND_CLAIM_READINESS,
            title="Claim-readiness check",
            body=(
                f"{gaps['items_with_gaps']} of your items are missing "
                "details an insurer asks for first: "
                + ", ".join(missing_bits)
                + ". Inventory -> Health Check lists exactly what's "
                "missing, item by item. You can silence these checks "
                "in Settings -> Notifications."
            ),
            data={"gaps": gaps},
            commit=False,
        )
        sent += 1
    db.commit()
    return sent
