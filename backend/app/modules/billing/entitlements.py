"""The entitlement engine (billing module service).

One question, one function: *what is this account allowed to do
right now?* `resolve_entitlement` folds every source — subscription
row, redeem/admin grants, trial windows, referral credit — into a
single answer, so the sources never fight each other and no caller
ever re-derives the rules.

SERVICE INTERFACE (stable; bump the billing manifest version on
change):
  - get_plan(db, plan_key) / list_plans(db) — the plan catalog.
  - bracket_for_employee_count(db, count) — Business bracket lookup.
  - get_setting(db, key, default) / set_setting(db, key, value)
  - enforcement_enabled(db) -> bool — the launch switch.
  - get_subscription(db, user_id) / upsert_subscription(...)
  - create_grant(...) — redeem codes and admin actions write here.
  - resolve_entitlement(db, user_id) -> Entitlement — THE answer.
  - active_tool_ids(db, user_id) -> set[UUID] | None — the shared
    active-set filter (None = no restriction). Every list surface
    (stats, sharing previews, peer views) consumes THIS function so
    inactive tools vanish consistently; the owner's own inventory
    list uses it to flag (grey) rather than hide.
  - active_battery_ids(db, user_id) -> set[UUID] | None — the
    battery half of the SAME active set: the plan's item limit
    covers ASSETS (tools + batteries together — a battery is an
    item in the vault), ranked newest-first as one stream, so the
    tool and battery halves always add up to the limit.
  - register_pin_provider(fn) / pinned_asset_ids(db, user_id) —
    the lapse-pin registry: a provider module (claims) registers a
    function returning the (tool ids, battery ids) that must stay
    active regardless of the limit; the active set unions them in
    on top of the newest-N slice, so a pinned item NEVER greys
    out while its pin holds.
  - asset_count(db, user_id) -> int — tools + batteries, the count
    the item limit and the Total Items stat are judged against.
  - can_add_tool(db, user_id) -> bool — the create doorway (counts
    all assets; the battery create route uses it too).
  - run_lapse_transitions(db) -> int — the daily-job seam.

ENFORCEMENT (owner decisions 2026-10-18): the machinery is built
now and switched ON at launch. While
`entitlements.enforcement_enabled` is False (the default), every
account is treated as unlimited — resolution still computes the
true plan for display, but active_tool_ids returns None and
can_add_tool always allows. Flipping the setting is the only change
launch day needs.

REFERRAL APPROXIMATION (honest note): the agreed rule is "every 5
referrals currently on a paying tier = 1 free month, re-evaluated
each cycle." Without Stripe there is no billing cycle to consume
months against, so v1 evaluates live: "paying" means the referred
account currently resolves to a paid plan by ANY means
(subscription or grant — its own referral credit excluded, so
referral chains can't bootstrap each other); when the earned months
>= 1 the referrer resolves to Pro through the end of the current
calendar month, and the earned-month count is reported on the
entitlement so the UI can show it. When Stripe lands, the monthly
job will consume banked months against real invoices instead.
"""

import calendar
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.billing import models

FREE_PLAN = "free"
REFERRALS_PER_FREE_MONTH = 5
ENFORCEMENT_KEY = "entitlements.enforcement_enabled"
# The email-verification launch switch (email flows, owner
# 2026-10-18). The key lives here with the other system-setting
# keys even though the READER is core's login route — system
# settings are one store with one vocabulary, and Admin →
# Settings edits it through the same surface as enforcement.
REQUIRE_EMAIL_VERIFICATION_KEY = "auth.require_email_verification"


# -- time helpers -------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """Normalize a DB timestamp to tz-aware UTC (SQLite returns naive)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def add_months(value: datetime, months: int) -> datetime:
    """Calendar month addition with day clamping (Jan 31 + 1 month
    = Feb 28/29), the way subscription periods actually behave."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


# -- plan catalog (config) ------------------------------------------------


def get_plan(db: Session, plan_key: str) -> models.Plan | None:
    return db.get(models.Plan, plan_key)


def list_plans(db: Session) -> list[models.Plan]:
    return list(
        db.scalars(select(models.Plan).order_by(models.Plan.sort_order)).all()
    )


def bracket_for_employee_count(
    db: Session, employee_count: int, plan_key: str = "business"
) -> models.BusinessBracket | None:
    """The bracket a shop's headcount falls into: the smallest
    bracket whose cap fits, else the open-ended (NULL cap) one."""
    brackets = list(
        db.scalars(
            select(models.BusinessBracket)
            .where(models.BusinessBracket.plan_key == plan_key)
            .order_by(models.BusinessBracket.sort_order)
        ).all()
    )
    for bracket in brackets:
        if bracket.up_to_employees is not None and employee_count <= bracket.up_to_employees:
            return bracket
    for bracket in brackets:
        if bracket.up_to_employees is None:
            return bracket
    return None


def _plan_rank(db: Session, plan_key: str) -> int:
    plan = get_plan(db, plan_key)
    return plan.sort_order if plan is not None else 0


# -- system settings --------------------------------------------------------


def get_setting(db: Session, key: str, default=None):
    row = db.get(models.SystemSetting, key)
    return default if row is None else row.value


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(models.SystemSetting, key)
    if row is None:
        db.add(models.SystemSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def enforcement_enabled(db: Session) -> bool:
    return bool(get_setting(db, ENFORCEMENT_KEY, False))


def email_verification_required(db: Session) -> bool:
    """The verification launch switch: when True, core's login
    route refuses unverified password-signup accounts (OAuth
    accounts are provider-verified at creation, so the flag never
    bites them). Default False — same posture as enforcement:
    built now, flipped at launch."""
    return bool(get_setting(db, REQUIRE_EMAIL_VERIFICATION_KEY, False))


# -- subscriptions ------------------------------------------------------------


def get_subscription(db: Session, user_id: uuid.UUID) -> models.Subscription | None:
    return db.scalars(
        select(models.Subscription).where(models.Subscription.user_id == user_id)
    ).first()


# -- status-change history ------------------------------------------------------
#
# Every write that moves a subscription's status appends one row
# to SubscriptionStatusChange (cancellation counts lane, owner
# 2026-11-07) — transitions only; a write that re-saves the same
# status records nothing. The writers are exactly: this module's
# upsert_subscription (the seam the webhook's subscription sync,
# the checkout placeholder, admin actions and tests feed),
# stripe_payments' two invoice handlers (which write the row
# directly and so call set_subscription_status), and
# run_lapse_transitions below. Grants and redeem codes never
# touch a subscription's status — they write EntitlementGrant
# rows — so they record nothing here by construction.

LIVE_SUBSCRIPTION_STATUSES = ("active", "trialing", "past_due")
TERMINAL_SUBSCRIPTION_STATUSES = ("canceled", "ended")


def is_cancellation_change(from_status: str | None, to_status: str) -> bool:
    """THE cancellation definition (printed on the admin
    Accounting report): a subscription leaving a live state
    (active | trialing | past_due) for a terminal state
    (canceled | ended) — counted once, when it first goes
    terminal. canceled -> ended (the lapse flip after a
    cancellation) starts from a terminal state, so it never
    counts as a second cancellation; a row CREATED in a
    terminal state (from_status None) never counted as live,
    so it does not count either."""
    return (
        from_status in LIVE_SUBSCRIPTION_STATUSES
        and to_status in TERMINAL_SUBSCRIPTION_STATUSES
    )


def record_status_change(
    db: Session,
    sub: models.Subscription,
    from_status: str | None,
    to_status: str,
    source: str,
) -> None:
    """Append the history row for one real transition. The
    caller commits; a same-status write records nothing."""
    if from_status == to_status:
        return
    db.add(
        models.SubscriptionStatusChange(
            subscription_id=sub.id,
            user_id=sub.user_id,
            from_status=from_status,
            to_status=to_status,
            source=source or "",
        )
    )


def set_subscription_status(
    db: Session,
    sub: models.Subscription,
    status: str,
    *,
    source: str,
) -> None:
    """Assign a subscription's status AND record the transition
    — the one door for writers that hold the row directly (the
    invoice handlers, the lapse job). The caller commits; a
    same-status assignment is a complete no-op."""
    if sub.status == status:
        return
    old = sub.status
    sub.status = status
    record_status_change(db, sub, old, status, source)


def upsert_subscription(
    db: Session,
    user_id: uuid.UUID,
    *,
    plan_key: str,
    status: str,
    source: str = "",
    current_period_end: datetime | None = None,
    grace_until: datetime | None = None,
    trial_end: datetime | None = None,
) -> models.Subscription:
    """Create or replace the user's subscription facts. This is the
    write seam Stripe webhooks (Phase C), admin actions, and tests
    all feed — the resolver never cares which. A status that
    actually changes is recorded in the status-change history
    (from_status None when the row is created); a same-status
    re-save records nothing."""
    sub = get_subscription(db, user_id)
    created = sub is None
    if created:
        sub = models.Subscription(user_id=user_id)
        db.add(sub)
        db.flush()
    old_status = None if created else sub.status
    sub.plan_key = plan_key
    sub.status = status
    sub.source = source
    sub.current_period_end = current_period_end
    sub.grace_until = grace_until
    sub.trial_end = trial_end
    record_status_change(db, sub, old_status, status, source)
    db.commit()
    db.refresh(sub)
    return sub


# -- grants -------------------------------------------------------------------


def create_grant(
    db: Session,
    user_id: uuid.UUID,
    *,
    plan_key: str = "pro",
    kind: str = "free_period",
    source: str = "",
    source_ref: str = "",
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    created_by: uuid.UUID | None = None,
) -> models.EntitlementGrant:
    grant = models.EntitlementGrant(
        user_id=user_id,
        plan_key=plan_key,
        kind=kind,
        source=source,
        source_ref=source_ref,
        starts_at=starts_at or _now(),
        ends_at=ends_at,
        created_by=created_by,
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return grant


def grant_period(
    db: Session,
    user_id: uuid.UUID,
    *,
    plan_key: str,
    kind: str,
    source: str,
    source_ref: str = "",
    months: int = 0,
    days: int = 0,
    created_by: uuid.UUID | None = None,
) -> models.EntitlementGrant:
    """Grant a plan for a span of time, STACKING on any still-active
    grant of the same plan: two free-month codes redeemed back to
    back give two months, not one month counted twice. The span
    starts at the later of now and the furthest end among the
    user's active same-plan grants."""
    now = _now()
    furthest = db.scalar(
        select(func.max(models.EntitlementGrant.ends_at)).where(
            models.EntitlementGrant.user_id == user_id,
            models.EntitlementGrant.plan_key == plan_key,
            models.EntitlementGrant.ends_at.is_not(None),
            models.EntitlementGrant.ends_at > now,
        )
    )
    start = max(now, _aware(furthest) or now)
    end = start
    if months:
        end = add_months(end, months)
    if days:
        end = end + timedelta(days=days)
    return create_grant(
        db,
        user_id,
        plan_key=plan_key,
        kind=kind,
        source=source,
        source_ref=source_ref,
        starts_at=start,
        ends_at=end,
        created_by=created_by,
    )


# -- resolution -------------------------------------------------------------


@dataclass
class Entitlement:
    """The one answer. `source` names what produced the winning
    entitlement (subscription | subscription_grace | trial |
    redeem_code | admin | lifetime | referral | free) so the UI and
    the audit trail can say WHY an account has what it has."""

    plan_key: str
    plan_name: str
    item_limit: int | None  # None = unlimited
    ai_monthly_credits: int
    is_paid: bool
    source: str
    referral_paying_count: int = 0
    referral_free_months: int = 0
    subscription: models.Subscription | None = field(default=None, repr=False)


def _subscription_candidate(
    sub: models.Subscription | None, now: datetime
) -> tuple[str, str, datetime | None] | None:
    """(plan_key, source, ends_at) the subscription currently
    confers, or None. The plan holds through the paid period, then
    through the grace window (owner: 20 days after Stripe gives
    up), then nothing — the drop to Free is computed, never a
    destructive flag flip someone has to remember to run."""
    if sub is None or sub.status in ("none", "ended"):
        return None
    period_end = _aware(sub.current_period_end)
    grace_until = _aware(sub.grace_until)
    trial_end = _aware(sub.trial_end)
    if sub.status == "trialing":
        # A trial confers the plan only inside its window. A lapsed
        # trial confers NOTHING (a converted trial arrives as status
        # "active" from the provider) — it must never fall through
        # to the open-ended branch below.
        if trial_end is None or trial_end > now:
            return (sub.plan_key, "trial", trial_end)
        return None
    deadline = grace_until or period_end
    if deadline is None:
        # Open-ended (manually managed) subscription: entitled.
        return (sub.plan_key, "subscription", None)
    if now <= deadline:
        source = (
            "subscription_grace"
            if period_end is not None and now > period_end
            else "subscription"
        )
        return (sub.plan_key, source, deadline)
    return None


def _referral_credit(db: Session, user_id: uuid.UUID, now: datetime) -> dict:
    """The referral rule, evaluated live (see the module docstring
    for the approximation). Returns the paying-referral count and
    the free months it currently earns."""
    # Lazy import: core's service owns user data; billing consumes
    # it through that interface (module law). Lazy so module load
    # order can never cycle.
    from app.modules.core import service as core_service

    paying = 0
    for referred in core_service.list_referred_users(db, user_id):
        theirs = resolve_entitlement(db, referred.id, include_referral=False, now=now)
        if theirs.is_paid:
            paying += 1
    return {
        "paying_count": paying,
        "free_months": paying // REFERRALS_PER_FREE_MONTH,
    }


def resolve_entitlement(
    db: Session,
    user_id: uuid.UUID,
    *,
    include_referral: bool = True,
    now: datetime | None = None,
) -> Entitlement:
    """THE effective-plan calculation. Sources are considered in
    the brief's order — subscription, redeem grants, admin grants,
    trial window, referral months — and the most generous valid one
    wins (plan rank, then the later end). `include_referral=False`
    is the anti-bootstrap reading used when evaluating whether a
    referred account itself counts as "paying"."""
    now = now or _now()
    uid = uuid.UUID(str(user_id))
    sub = get_subscription(db, uid)

    # (rank, ends-at sort key, plan_key, source); ends None = forever.
    candidates: list[tuple[int, float, str, str]] = []

    def consider(plan_key: str, source: str, ends_at: datetime | None) -> None:
        ends_key = ends_at.timestamp() if ends_at is not None else float("inf")
        candidates.append((_plan_rank(db, plan_key), ends_key, plan_key, source))

    sub_candidate = _subscription_candidate(sub, now)
    if sub_candidate is not None:
        consider(*sub_candidate)

    grants = db.scalars(
        select(models.EntitlementGrant).where(
            models.EntitlementGrant.user_id == uid,
            models.EntitlementGrant.starts_at <= now,
        )
    ).all()
    for grant in grants:
        ends_at = _aware(grant.ends_at)
        if ends_at is not None and ends_at <= now:
            continue
        source = (
            "lifetime"
            if grant.kind == "lifetime"
            else "trial"
            if grant.kind == "trial"
            else grant.source or "grant"
        )
        consider(grant.plan_key, source, ends_at)

    referral = {"paying_count": 0, "free_months": 0}
    if include_referral:
        referral = _referral_credit(db, uid, now)
        if referral["free_months"] >= 1:
            # Earned months confer Pro through the current calendar
            # month's end (the live-evaluation approximation).
            month_end = add_months(now.replace(day=1), 1)
            consider("pro", "referral", month_end)

    if candidates:
        _, _, plan_key, source = max(candidates)
    else:
        plan_key, source = FREE_PLAN, "free"
    plan = get_plan(db, plan_key)
    return Entitlement(
        plan_key=plan_key,
        plan_name=plan.name if plan else plan_key,
        item_limit=plan.item_limit if plan else 20,
        ai_monthly_credits=plan.ai_monthly_credits if plan else 0,
        is_paid=bool(plan.is_paid) if plan else plan_key != FREE_PLAN,
        source=source,
        referral_paying_count=referral["paying_count"],
        referral_free_months=referral["free_months"],
        subscription=sub,
    )


# -- pinned items (the claims seam) -------------------------------------------
#
# A pin provider answers one question for one owner: which of their
# asset ids must stay active regardless of the item limit? The
# claims module registers its provider at import (items targeted
# by an OPEN claim — filed / in review / approved — stay active:
# evidence in a live claim must never grey out mid-claim, owner
# rule from the blueprint). The registry is the whole connection —
# this module never imports the provider's module, so removing the
# provider module removes the pins with it, and accounts without
# the provider behave exactly as before it existed.

PinProvider = Callable[[Session, uuid.UUID], tuple[set[uuid.UUID], set[uuid.UUID]]]

_pin_providers: list[PinProvider] = []


def register_pin_provider(provider: PinProvider) -> None:
    """Register a lapse-pin provider. Idempotent by identity, so a
    module re-import never double-registers."""
    if provider not in _pin_providers:
        _pin_providers.append(provider)


def pinned_asset_ids(
    db: Session, user_id: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """The union of every registered provider's pins for this
    owner: (tool ids, battery ids). Empty when no provider is
    registered — the pre-claims behavior."""
    tools: set[uuid.UUID] = set()
    batteries: set[uuid.UUID] = set()
    uid = uuid.UUID(str(user_id))
    for provider in _pin_providers:
        pin_tools, pin_batteries = provider(db, uid)
        tools |= set(pin_tools)
        batteries |= set(pin_batteries)
    return tools, batteries


# -- the active set ----------------------------------------------------------


def _tool_model():
    # Lazy: inventory owns the tools table; billing reads it for the
    # active-set computation only (ids + created_at, nothing more).
    from app.modules.inventory import models as inventory_models

    return inventory_models.Tool


def _asset_models():
    # Lazy, same discipline as _tool_model: billing reads ids +
    # created_at from both asset tables, nothing more.
    from app.modules.inventory import models as inventory_models

    return inventory_models.Tool, inventory_models.Battery


def tool_count(db: Session, user_id: uuid.UUID) -> int:
    tool = _tool_model()
    return (
        db.scalar(
            select(func.count(tool.id)).where(tool.owner_id == uuid.UUID(str(user_id)))
        )
        or 0
    )


def asset_count(db: Session, user_id: uuid.UUID) -> int:
    """Tools + batteries: an account's ITEM count. Batteries are
    assets in the vault (owner spec 2026-10-18), so the plan's item
    limit — and the Total Items stat — are judged against this.

    SETS count once (the set IS one tool record); tools ATTACHED
    into a set don't count while attached, and set pieces are not
    assets at all (item structure package, 2026-10-18)."""
    tool, battery = _asset_models()
    uid = uuid.UUID(str(user_id))
    # SOLD items (wave 2) are gone from the owner's world: they
    # hold no plan slot and count toward nothing here — the sale
    # freed the slot the moment it was recorded.
    tools = db.scalar(
        select(func.count(tool.id)).where(
            tool.owner_id == uid,
            tool.attached_to_set_id.is_(None),
            tool.standing.notin_(("sold", "replaced")),
        )
    ) or 0
    batteries = (
        db.scalar(
            select(func.count(battery.id)).where(
                battery.owner_id == uid,
                battery.standing.notin_(("sold", "replaced")),
            )
        )
        or 0
    )
    return tools + batteries


def _active_asset_ids(
    db: Session, user_id: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID]] | None:
    """The shared active set, split by kind: (active tool ids,
    active battery ids), or None when nothing is restricted
    (enforcement off, an unlimited plan, or the account is within
    its limit).

    The limit covers ASSETS as ONE newest-first stream across both
    tables — 18 tools + 5 batteries on a 20-item plan keeps the 20
    newest assets active regardless of kind. Computed, never
    stored — a plan change re-derives it on the next read, and no
    row is ever mutated by a lapse.

    PINS (the claims seam, wired 2026-10-19): on top of the slice,
    the ids returned by the registered pin providers (see
    pinned_asset_ids) are unioned in — an item pinned by an open
    insurance claim stays active REGARDLESS of the recency cut,
    in addition to the slice, never instead of one of its slots.
    """
    if not enforcement_enabled(db):
        return None
    entitlement = resolve_entitlement(db, user_id)
    if entitlement.item_limit is None:
        return None
    if asset_count(db, user_id) <= entitlement.item_limit:
        return None
    tool, battery = _asset_models()
    uid = uuid.UUID(str(user_id))
    stream: list[tuple[object, str, uuid.UUID]] = []
    for model, kind in ((tool, "tool"), (battery, "battery")):
        stmt = select(model.id, model.created_at).where(
            model.owner_id == uid,
            # Sold items never enter the stream (wave 2): they
            # consume no slot and are in nobody's active set.
            model.standing.notin_(("sold", "replaced")),
        )
        if kind == "tool":
            # Attached addon tools hold NO active slot of their own:
            # they live and grey with their set (which holds one).
            stmt = stmt.where(model.attached_to_set_id.is_(None))
        rows = db.execute(stmt).all()
        stream.extend((created_at, kind, row_id) for row_id, created_at in rows)
    # Newest first; id breaks created_at ties deterministically,
    # the same rule the tool-only version used.
    stream.sort(key=lambda entry: (entry[0], str(entry[2])), reverse=True)
    kept = stream[: entitlement.item_limit]
    pin_tools, pin_batteries = pinned_asset_ids(db, user_id)
    return (
        {row_id for _, kind, row_id in kept if kind == "tool"} | pin_tools,
        {row_id for _, kind, row_id in kept if kind == "battery"} | pin_batteries,
    )


def active_tool_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID] | None:
    """The tool half of the shared active set (see _active_asset_ids):
    the ids of the user's ACTIVE tools, or None when nothing is
    restricted."""
    active = _active_asset_ids(db, user_id)
    return None if active is None else active[0]


def active_battery_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID] | None:
    """The battery half of the shared active set (see
    _active_asset_ids): the ids of the user's ACTIVE batteries, or
    None when nothing is restricted."""
    active = _active_asset_ids(db, user_id)
    return None if active is None else active[1]


def can_add_tool(db: Session, user_id: uuid.UUID) -> bool:
    """The create doorway: with enforcement on, an account at its
    plan's item limit cannot add another item — tool OR battery
    (the client routes the refusal to the upgrade prompt).
    Enforcement off or an unlimited plan always allows."""
    if not enforcement_enabled(db):
        return True
    entitlement = resolve_entitlement(db, user_id)
    if entitlement.item_limit is None:
        return True
    return asset_count(db, user_id) < entitlement.item_limit


# -- lapse machinery -----------------------------------------------------------


def run_lapse_transitions(db: Session, now: datetime | None = None) -> int:
    """The daily-job seam: flip subscriptions whose paid period AND
    grace window have both passed to status "ended". Resolution
    already computes the drop to Free without this — the flip only
    keeps the stored facts honest for the admin views and future
    warning emails. Returns how many subscriptions transitioned.

    SCHEDULING: there is no scheduler in the codebase yet; this
    function (and wallet.refill_all_allowances) is the seam a cron
    / management command calls — see app/scripts/run_entitlement_jobs.py.
    """
    now = now or _now()
    transitioned = 0
    subs = db.scalars(
        select(models.Subscription).where(
            models.Subscription.status.in_(
                ["active", "trialing", "past_due", "canceled"]
            )
        )
    ).all()
    for sub in subs:
        deadline = _aware(sub.grace_until) or _aware(sub.current_period_end)
        if deadline is not None and now > deadline:
            set_subscription_status(db, sub, "ended", source="lapse_job")
            transitioned += 1
    if transitioned:
        db.commit()
    return transitioned
