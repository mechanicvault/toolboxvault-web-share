"""Admin report datasets (admin lane, owner 2026-11-06).

Builders for the ADMIN_TYPES catalog entries — site-wide
datasets a god / moderator_admin seat generates through the
ordinary reports machinery (same templates, same History, same
viewer; the routes gate the types and the catalog keeps them
out of every member surface). Each builder returns the tabular
shape reports/tabular.py renders: counts and text, honestly
labeled — the numbers come from core/site_stats (whose module
docstring states which figures derive from timestamps and
which ride the daily snapshot) and the inventory module's own
per-owner stats, so an admin total always matches what the
member's own Home shows for that member.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.billing import entitlements as billing_entitlements
from app.modules.billing import models as billing_models
from app.modules.core import models as core_models
from app.modules.core import money, site_stats, tiers
from app.modules.inventory import service as inventory_service

_TIER_ORDER = ("god", "moderator_admin", "moderator", "normal")
_TIER_LABELS = {
    "god": "God",
    "moderator_admin": "Moderator admin",
    "moderator": "Moderator",
    "normal": "Member",
}
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _fmt(amount, currency: str) -> str:
    return money.format_money(Decimal(amount), currency)


def _day(value: datetime | None) -> str:
    return value.strftime("%m/%d/%Y") if value is not None else "—"


def _all_users(db: Session) -> list[core_models.User]:
    return list(
        db.scalars(
            select(core_models.User).order_by(core_models.User.created_at)
        ).all()
    )


def _subscriptions(db: Session) -> dict:
    """user_id -> (subscription, plan) for every subscription row."""
    plans = {
        p.plan_key: p for p in db.scalars(select(billing_models.Plan)).all()
    }
    out = {}
    for sub in db.scalars(select(billing_models.Subscription)).all():
        out[sub.user_id] = (sub, plans.get(sub.plan_key))
    return out


_TYPE_LABELS = {
    "mechanic": "Mechanic",
    "shop": "Shop",
    "insurance": "Insurance",
    "agent": "Agent",
}


def build_site_stats(db: Session, owner, settings: dict) -> dict:
    currency = owner.currency or "USD"
    facts = site_stats.current_facts(db)
    by_tier = facts["users_by_tier"]
    tier_rows = [
        [_TIER_LABELS.get(rung, rung), str(by_tier.get(rung, 0))]
        for rung in _TIER_ORDER
    ]
    by_type = facts["users_by_type"]
    type_rows = [
        [_TYPE_LABELS.get(key, key), str(by_type.get(key, 0))]
        for key in site_stats.MEMBER_TYPE_KEYS
    ]
    plan_rows = [
        ["Paying", str(facts["paying_users"])],
        ["Free", str(facts["free_users"])],
    ]
    for entry in facts["paying_by_plan"]:
        plan_rows.append(
            [f"{entry['name']} — monthly", str(entry["monthly"])]
        )
        plan_rows.append(
            [f"{entry['name']} — annual", str(entry["annual"])]
        )
    return {
        "title": "Site overview",
        "subtitle": (
            "Live counts as of today. Day-over-day movement rides "
            "the daily snapshot — see the Site Stats widget on Home. "
            "Member types: an account counts in every type it "
            "holds, so those rows can add up past the member total; "
            "“Agent” counts registered agents only."
        ),
        "banner": [
            f"MEMBERS {facts['users_total']}",
            f"PAYING {facts['paying_users']}",
            f"MRR {_fmt(facts['mrr'], currency)}",
            f"TOOLS LOGGED {facts['tools_total']}",
        ],
        "sections": [
            {
                "label": "Members by tier",
                "columns": ["Tier", "Members"],
                "rows": tier_rows,
                "total": f"TOTAL: {facts['users_total']} members",
            },
            {
                "label": "Members by type",
                "columns": ["Type", "Members"],
                "rows": type_rows,
                "total": f"TOTAL: {facts['users_total']} members",
            },
            {
                "label": "Plans",
                "columns": ["", "Accounts"],
                "rows": plan_rows,
                "total": f"MRR: {_fmt(facts['mrr'], currency)}",
            },
            {
                "label": "Today",
                "columns": ["", "Count"],
                "rows": [
                    ["New members today", str(facts["new_users"])],
                    ["New paying accounts today", str(facts["new_paid"])],
                    ["Tools logged today", str(facts["tools_logged"])],
                ],
                "total": None,
            },
        ],
    }


def build_users(db: Session, owner, settings: dict) -> dict:
    users = _all_users(db)
    rows = []
    for user in users:
        stats = inventory_service.get_inventory_stats(db, user.id)
        rows.append(
            [
                user.name,
                user.account_number or "—",
                user.email,
                _TIER_LABELS.get(tiers.resolved_tier(user), ""),
                _day(user.created_at),
                str(stats["total_items"]),
            ]
        )
    return {
        "title": "User directory",
        "subtitle": "Every member account on the site.",
        "banner": [f"MEMBERS {len(users)}"],
        "sections": [
            {
                "label": "Members",
                "columns": [
                    "Name", "Account", "Email", "Tier", "Joined", "Tools",
                ],
                "rows": rows,
                "total": f"TOTAL: {len(users)} members",
            }
        ],
    }


def build_inventory(db: Session, owner, settings: dict) -> dict:
    currency = owner.currency or "USD"
    users = _all_users(db)
    rows = []
    total_items = 0
    total_value = Decimal("0")
    for user in users:
        stats = inventory_service.get_inventory_stats(db, user.id)
        total_items += stats["total_items"]
        total_value += Decimal(stats["total_value"])
        rows.append(
            [
                user.name,
                user.account_number or "—",
                str(stats["total_items"]),
                _fmt(stats["total_value"], currency),
            ]
        )
    return {
        "title": "Inventory across the site",
        "subtitle": (
            "Per-member item counts and purchase-cost values — the "
            "same numbers each member's own Home shows."
        ),
        "banner": [
            f"ITEMS {total_items}",
            f"VALUE {_fmt(total_value, currency)}",
        ],
        "sections": [
            {
                "label": "Members",
                "columns": ["Name", "Account", "Items", "Value"],
                "rows": rows,
                "total": (
                    f"TOTAL: {total_items} items · "
                    f"{_fmt(total_value, currency)}"
                ),
            }
        ],
    }


def build_payments(db: Session, owner, settings: dict) -> dict:
    currency = owner.currency or "USD"
    users = _all_users(db)
    subs = _subscriptions(db)
    rows = []
    paying = 0
    mrr = Decimal("0")
    for user in users:
        entry = subs.get(user.id)
        if entry is None:
            rows.append(
                [user.name, user.account_number or "—", "Free", "—", "Free", "—"]
            )
            continue
        sub, plan = entry
        plan_name = plan.name if plan is not None else sub.plan_key
        is_paying = (
            plan is not None and plan.is_paid and sub.status == "active"
        )
        monthly = site_stats.monthly_equivalent(db, sub)
        if is_paying:
            paying += 1
            mrr += monthly
        rows.append(
            [
                user.name,
                user.account_number or "—",
                plan_name,
                sub.status,
                "Paying" if is_paying else "Free",
                _fmt(monthly, currency) if is_paying else "—",
            ]
        )
    return {
        "title": "Payment accounts",
        "subtitle": (
            "Plans and subscription state for every member. Monthly "
            "figures use the site's current plan prices."
        ),
        "banner": [f"PAYING {paying}", f"MRR {_fmt(mrr, currency)}"],
        "sections": [
            {
                "label": "Accounts",
                "columns": [
                    "Name", "Account", "Plan", "Status", "Kind", "Monthly",
                ],
                "rows": rows,
                "total": f"TOTAL: {paying} paying · MRR {_fmt(mrr, currency)}",
            }
        ],
    }


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime.combine(date(year, month, 1), time.min, tzinfo=timezone.utc)
    if month == 12:
        end = datetime.combine(date(year + 1, 1, 1), time.min, tzinfo=timezone.utc)
    else:
        end = datetime.combine(
            date(year, month + 1, 1), time.min, tzinfo=timezone.utc
        )
    return start, end


def _new_paid_in(db: Session, start: datetime, end: datetime) -> tuple[int, Decimal]:
    """(count, monthly-equivalent added) for paid subscriptions
    created in [start, end) — derived from subscription creation
    timestamps; the money uses current plan prices (the same
    reading site_stats gives MRR)."""
    plans = {
        p.plan_key: p for p in db.scalars(select(billing_models.Plan)).all()
    }
    count = 0
    added = Decimal("0")
    for sub in db.scalars(
        select(billing_models.Subscription).where(
            billing_models.Subscription.created_at >= start,
            billing_models.Subscription.created_at < end,
            billing_models.Subscription.status != "none",
        )
    ).all():
        plan = plans.get(sub.plan_key)
        if plan is None or not plan.is_paid:
            continue
        count += 1
        added += site_stats.monthly_equivalent(db, sub)
    return count, added


def build_revenue_year(db: Session, owner, settings: dict) -> dict:
    currency = owner.currency or "USD"
    year = int((settings or {}).get("year") or date.today().year)
    rows = []
    total_count = 0
    total_added = Decimal("0")
    for month in range(1, 13):
        start, end = _month_bounds(year, month)
        count, added = _new_paid_in(db, start, end)
        total_count += count
        total_added += added
        rows.append(
            [_MONTHS[month - 1], str(count), _fmt(added, currency)]
        )
    facts = site_stats.current_facts(db)
    return {
        "title": f"Revenue by month — {year}",
        "subtitle": (
            "New paying accounts per month, and the monthly "
            "recurring revenue those signups added (at today's "
            "plan prices). Churn is not netted — this is the "
            "signups ledger, not a bank statement."
        ),
        "banner": [
            f"NEW PAYING IN {year} {total_count}",
            f"CURRENT MRR {_fmt(facts['mrr'], currency)}",
        ],
        "sections": [
            {
                "label": str(year),
                "columns": ["Month", "New paying accounts", "MRR added"],
                "rows": rows,
                "total": (
                    f"TOTAL: {total_count} new paying · "
                    f"{_fmt(total_added, currency)} added"
                ),
            }
        ],
    }


def build_revenue_quarter(db: Session, owner, settings: dict) -> dict:
    currency = owner.currency or "USD"
    year = int((settings or {}).get("year") or date.today().year)
    rows = []
    total_count = 0
    total_added = Decimal("0")
    for quarter in range(4):
        start, _ = _month_bounds(year, quarter * 3 + 1)
        _, end = _month_bounds(year, quarter * 3 + 3)
        count, added = _new_paid_in(db, start, end)
        total_count += count
        total_added += added
        rows.append(
            [f"Q{quarter + 1}", str(count), _fmt(added, currency)]
        )
    facts = site_stats.current_facts(db)
    return {
        "title": f"Revenue by quarter — {year}",
        "subtitle": (
            "New paying accounts per quarter, and the monthly "
            "recurring revenue those signups added (at today's "
            "plan prices). Churn is not netted — this is the "
            "signups ledger, not a bank statement."
        ),
        "banner": [
            f"NEW PAYING IN {year} {total_count}",
            f"CURRENT MRR {_fmt(facts['mrr'], currency)}",
        ],
        "sections": [
            {
                "label": str(year),
                "columns": ["Quarter", "New paying accounts", "MRR added"],
                "rows": rows,
                "total": (
                    f"TOTAL: {total_count} new paying · "
                    f"{_fmt(total_added, currency)} added"
                ),
            }
        ],
    }


def _aware(value: datetime) -> datetime:
    """Row timestamps as aware UTC (Postgres hands back aware
    values, SQLite naive ones — the site_stats rule)."""
    return value if value.tzinfo is not None else value.replace(
        tzinfo=timezone.utc
    )


def _period(settings: dict) -> tuple[date | None, date, str]:
    """The effective range for a period-settings report: the
    wizard's start/end when given; a missing start reads as
    "from the beginning", a missing end as today. The label
    prints the range the figures actually cover."""
    raw_start = (settings or {}).get("start")
    raw_end = (settings or {}).get("end")
    start = date.fromisoformat(str(raw_start)) if raw_start else None
    end = date.fromisoformat(str(raw_end)) if raw_end else date.today()
    start_label = (
        start.strftime("%b %d, %Y") if start else "From the beginning"
    )
    return start, end, f"{start_label} – {end.strftime('%b %d, %Y')}"


def _period_bounds(
    start: date | None, end: date
) -> tuple[datetime, datetime]:
    """Half-open [lo, hi) instants covering the period's days."""
    lo = (
        datetime.combine(start, time.min, tzinfo=timezone.utc)
        if start
        else datetime.min.replace(tzinfo=timezone.utc)
    )
    hi = datetime.combine(end, time.min, tzinfo=timezone.utc) + timedelta(
        days=1
    )
    return lo, hi


# Subscription status changes are recorded as they happen
# from this day forward (migration 0088, the cancellation
# counts lane) — no earlier change exists anywhere, so a
# period reaching back to or before this date can only count
# the recorded part of itself, and the Accounting report
# prints that rider rather than a bare misleading number.
_STATUS_RECORDING_START = date(2026, 11, 7)


def build_accounting(db: Session, owner, settings: dict) -> dict:
    """The one go-to payment report (admin polish lane, owner
    2026-11-07): everything the subscription data honestly
    supports for a chosen period, each figure labeled with
    what it counts. Money uses today's plan prices (the same
    reading as MRR everywhere). One thing the stored data
    CANNOT say, stated on the document rather than faked:
    card transactions (Stripe is not live — none exist).
    Cancellations ARE counted — from the status-change
    history (migration 0088), which records every transition
    as it happens from 2026-11-07 forward; the definition is
    printed on the document, and a period reaching back
    before recording began carries the rider saying its
    count covers only the recorded part."""
    currency = owner.currency or "USD"
    start, end, period_label = _period(settings)
    lo, hi = _period_bounds(start, end)
    facts = site_stats.current_facts(db)
    plans = list(db.scalars(select(billing_models.Plan)).all())
    subs = list(db.scalars(select(billing_models.Subscription)).all())
    active_users = [
        user for user in _all_users(db) if user.is_active
    ]

    # Accounts by plan (current state). A paid plan's row
    # counts its own subscription rows; an unpaid plan's row
    # counts the active accounts that hold no paid-plan row at
    # all — so the Not paying column reconciles with the free
    # count instead of reading 0 for the plan most accounts
    # are on.
    subs_by_user = {sub.user_id: sub for sub in subs}
    paid_keys = {plan.plan_key for plan in plans if plan.is_paid}
    plan_rows = []
    for plan in plans:
        mine = [sub for sub in subs if sub.plan_key == plan.plan_key]
        paying_rows = [
            sub
            for sub in mine
            if plan.is_paid and sub.status == "active"
        ]
        if plan.is_paid:
            not_paying = len(mine) - len(paying_rows)
        else:
            not_paying = len(
                [
                    user
                    for user in active_users
                    if subs_by_user.get(user.id) is None
                    or subs_by_user[user.id].plan_key not in paid_keys
                ]
            )
        contribution = sum(
            (site_stats.monthly_equivalent(db, sub) for sub in paying_rows),
            Decimal("0"),
        )
        plan_rows.append(
            [
                plan.name,
                str(len(paying_rows)),
                str(not_paying),
                _fmt(contribution, currency) if plan.is_paid else "—",
            ]
        )

    # Subscription states (current state, active accounts).
    state_counts: dict[str, int] = {}
    for user in active_users:
        sub = subs_by_user.get(user.id)
        state = sub.status if sub is not None else "no_subscription"
        state_counts[state] = state_counts.get(state, 0) + 1
    _STATE_LABELS = {
        "active": "Active",
        "trialing": "Trialing",
        "past_due": "Past due",
        "canceled": "Canceled (current state)",
        "ended": "Ended (current state)",
        "none": "None (checkout placeholder)",
        "no_subscription": "No subscription (free)",
    }
    state_rows = [
        [_STATE_LABELS.get(state, state), str(count)]
        for state, count in sorted(
            state_counts.items(), key=lambda item: -item[1]
        )
    ]

    # In the period.
    new_accounts = len(
        [
            user
            for user in _all_users(db)
            if user.created_at is not None
            and lo <= _aware(user.created_at) < hi
        ]
    )
    new_paid_count, new_paid_added = _new_paid_in(db, lo, hi)
    # Cancellations in the period, from the status-change
    # history: transitions the one definition counts (a live
    # state reaching a terminal state), timestamped inside
    # the period. A period that starts on or before the day
    # recording began reaches into unrecorded time — its
    # count covers only the recorded part, and the subtitle
    # says so (see below) instead of the number standing bare.
    changes_in_period = list(
        db.scalars(
            select(billing_models.SubscriptionStatusChange)
            .where(
                billing_models.SubscriptionStatusChange.created_at >= lo,
                billing_models.SubscriptionStatusChange.created_at < hi,
            )
        ).all()
    )
    cancellations = sum(
        1
        for change in changes_in_period
        if billing_entitlements.is_cancellation_change(
            change.from_status, change.to_status
        )
    )
    period_reaches_unrecorded = (
        start is None or start <= _STATUS_RECORDING_START
    )
    period_rows = [
        ["New accounts created", str(new_accounts), "—"],
        [
            "New paying accounts",
            str(new_paid_count),
            _fmt(new_paid_added, currency),
        ],
        ["Cancellations", str(cancellations), "—"],
    ]
    for plan in plans:
        if not plan.is_paid:
            continue
        mine = [
            sub
            for sub in subs
            if sub.plan_key == plan.plan_key
            and sub.status != "none"
            and sub.created_at is not None
            and lo <= _aware(sub.created_at) < hi
        ]
        if not mine:
            continue
        added = sum(
            (site_stats.monthly_equivalent(db, sub) for sub in mine),
            Decimal("0"),
        )
        period_rows.append(
            [
                f"New paying — {plan.name}",
                str(len(mine)),
                _fmt(added, currency),
            ]
        )

    # MRR at period end: a state figure, so it comes from the
    # daily snapshot when the period ends in the past; today's
    # MRR when the period ends today or later; "Not recorded"
    # when no snapshot reaches back that far.
    if end >= date.today():
        mrr_end = _fmt(facts["mrr"], currency)
    else:
        snapshot = db.scalars(
            select(core_models.SiteStatsSnapshot)
            .where(core_models.SiteStatsSnapshot.day <= end)
            .order_by(core_models.SiteStatsSnapshot.day.desc())
            .limit(1)
        ).first()
        if snapshot is not None:
            mrr_end = (
                f"{_fmt((snapshot.payload or {}).get('mrr', '0'), currency)}"
                f" (daily snapshot, {snapshot.day.strftime('%b %d, %Y')})"
            )
        else:
            mrr_end = "Not recorded"

    # Subtitle order is the natural reading order: the
    # report's general preamble first, then the cancellation
    # definition, then — for a period reaching back before
    # recording began — the rider qualifying the count. The
    # cancellation lane originally FRONT-LOADED the
    # rider/definition because the tabular PDF renderer drew
    # the subtitle as one non-wrapping line and only its
    # first line printed; the renderer wraps now
    # (pdf-subtitle-wrap lane, 2026-11-07), the whole
    # subtitle prints in every format, and the order is free
    # to read naturally again. The sentences are unchanged.
    definition = (
        "Cancellations: a subscription reaching canceled "
        "or ended from active, trialing, or past due, "
        "counted once when it first goes terminal. "
        "Subscription status changes are recorded as they "
        "happen since November 7, 2026."
    )
    preamble = (
        "Every payment-related figure the subscription data "
        "honestly supports, at the plan prices in effect "
        "today. Stripe card payments aren't live yet, so "
        "there are no card transactions to report — this is "
        "the subscription ledger, not a bank statement."
    )
    rider = (
        "Cancellations here cover only the recorded "
        "part: status changes are recorded since "
        "November 7, 2026; earlier ones were never "
        "recorded."
    )
    if period_reaches_unrecorded:
        subtitle = preamble + " " + definition + " " + rider
    else:
        subtitle = preamble + " " + definition
    return {
        "title": "Accounting",
        "subtitle": subtitle,
        "banner": [
            f"PERIOD {period_label.upper()}",
            f"PAYING {facts['paying_users']}",
            f"MRR {_fmt(facts['mrr'], currency)}",
        ],
        "sections": [
            {
                "label": "Accounts by plan (today)",
                "columns": ["Plan", "Paying", "Not paying", "Monthly revenue"],
                "rows": plan_rows,
                "total": (
                    f"TOTAL: {facts['paying_users']} paying · "
                    f"MRR {_fmt(facts['mrr'], currency)}"
                ),
            },
            {
                "label": "Subscription states (today)",
                "columns": ["State", "Accounts"],
                "rows": state_rows,
                "total": f"TOTAL: {len(active_users)} active accounts",
            },
            {
                "label": f"In the period — {period_label}",
                "columns": ["", "Count", "Monthly value added"],
                "rows": period_rows,
                "total": None,
            },
            {
                "label": "Monthly recurring revenue",
                "columns": ["", "Amount"],
                "rows": [
                    ["MRR today", _fmt(facts["mrr"], currency)],
                    [f"MRR at period end ({end.strftime('%b %d, %Y')})", mrr_end],
                ],
                "total": None,
            },
        ],
    }


_AI_ACTION_LABELS = {
    "lookup": "Catalog lookup",
    "identify": "Identify (text + photo)",
    "manual_lookup": "Manual lookup",
    "report_summary": "Report summary",
    "drawer_lookup": "Drawer lookup",
}

_AI_ACCOUNT_ROW_CAP = 100


def build_ai_usage(db: Session, owner, settings: dict) -> dict:
    """AI usage from the metering table (admin polish lane,
    owner 2026-11-07): site totals, per-action totals, then one
    section per account with every recorded action — when, how
    (which metered action), what for (the recorded subject),
    tokens, and wallet credits charged. Recording began with
    migration 0087; the subtitle says so on the document, and
    an empty period reads as an empty period, never as zeros
    dressed up as history."""
    start, end, period_label = _period(settings)
    lo, hi = _period_bounds(start, end)
    rows = list(
        db.scalars(
            select(billing_models.AiUsage)
            .where(
                billing_models.AiUsage.created_at >= lo,
                billing_models.AiUsage.created_at < hi,
            )
            .order_by(billing_models.AiUsage.created_at)
        ).all()
    )
    earliest = db.scalar(
        select(billing_models.AiUsage.created_at)
        .order_by(billing_models.AiUsage.created_at)
        .limit(1)
    )
    if earliest is None:
        subtitle = (
            "AI usage recording began with the November 2026 "
            "admin update — before it, AI calls at the default "
            "price of 0 left no record anywhere, and none has "
            "been recorded since yet."
        )
    else:
        subtitle = (
            f"AI usage recording began {_day(earliest)} — calls "
            "before then weren't recorded (the wallet ledger only "
            "ever kept paid charges). Charges are AI-wallet "
            "credits; token counts are the providers' own."
        )
    users = {user.id: user for user in _all_users(db)}
    total_calls = sum(row.calls for row in rows)
    tokens_in = sum(row.tokens_in for row in rows)
    tokens_out = sum(row.tokens_out for row in rows)
    credits = sum(row.credits_charged for row in rows)
    accounts = len({row.user_id for row in rows})

    sections = [
        {
            "label": "Site totals",
            "columns": ["", "Total"],
            "rows": [
                ["AI actions recorded", str(len(rows))],
                ["Provider calls", str(total_calls)],
                ["Tokens in", f"{tokens_in:,}"],
                ["Tokens out", f"{tokens_out:,}"],
                ["Wallet credits charged", str(credits)],
                ["Accounts that used AI", str(accounts)],
            ],
            "total": None,
        }
    ]
    if rows:
        by_action: dict[str, list] = {}
        for row in rows:
            by_action.setdefault(row.action, []).append(row)
        action_rows = []
        for action in list(_AI_ACTION_LABELS) + sorted(
            key for key in by_action if key not in _AI_ACTION_LABELS
        ):
            mine = by_action.get(action)
            if not mine:
                continue
            action_rows.append(
                [
                    _AI_ACTION_LABELS.get(action, action),
                    str(len(mine)),
                    f"{sum(r.tokens_in for r in mine):,}",
                    f"{sum(r.tokens_out for r in mine):,}",
                    str(sum(r.credits_charged for r in mine)),
                ]
            )
        sections.append(
            {
                "label": "By action",
                "columns": [
                    "Action", "Uses", "Tokens in", "Tokens out", "Credits",
                ],
                "rows": action_rows,
                "total": (
                    f"TOTAL: {len(rows)} actions · "
                    f"{tokens_in + tokens_out:,} tokens · {credits} credits"
                ),
            }
        )
        by_user: dict = {}
        for row in rows:
            by_user.setdefault(row.user_id, []).append(row)
        ordered = sorted(
            by_user.items(),
            key=lambda item: -sum(
                r.tokens_in + r.tokens_out for r in item[1]
            ),
        )
        for user_id, mine in ordered:
            user = users.get(user_id)
            name = user.name if user is not None else "Deleted account"
            number = (
                user.account_number
                if user is not None and user.account_number
                else "—"
            )
            detail_rows = [
                [
                    row.created_at.strftime("%m/%d/%Y %H:%M")
                    if row.created_at
                    else "—",
                    _AI_ACTION_LABELS.get(row.action, row.action),
                    row.subject or "—",
                    f"{row.tokens_in:,}",
                    f"{row.tokens_out:,}",
                    str(row.credits_charged),
                ]
                for row in mine[:_AI_ACCOUNT_ROW_CAP]
            ]
            if len(mine) > _AI_ACCOUNT_ROW_CAP:
                detail_rows.append(
                    [
                        "…",
                        f"{len(mine) - _AI_ACCOUNT_ROW_CAP} more actions",
                        "",
                        "",
                        "",
                        "",
                    ]
                )
            sections.append(
                {
                    "label": f"{name} ({number})",
                    "columns": [
                        "When", "Action", "What for",
                        "Tokens in", "Tokens out", "Credits",
                    ],
                    "rows": detail_rows,
                    "total": (
                        f"TOTAL: {len(mine)} actions · "
                        f"{sum(r.tokens_in + r.tokens_out for r in mine):,} "
                        f"tokens · "
                        f"{sum(r.credits_charged for r in mine)} credits"
                    ),
                }
            )
    else:
        sections.append(
            {
                "label": "Usage in this period",
                "columns": [
                    "When", "Action", "What for",
                    "Tokens in", "Tokens out", "Credits",
                ],
                "rows": [
                    ["No AI usage was recorded in this period.", "", "", "", "", ""]
                ],
                "total": None,
            }
        )
    return {
        "title": "AI usage",
        "subtitle": subtitle,
        "banner": [
            f"PERIOD {period_label.upper()}",
            f"ACTIONS {len(rows)}",
            f"TOKENS {tokens_in + tokens_out:,}",
            f"CREDITS CHARGED {credits}",
        ],
        "sections": sections,
    }


BUILDERS = {
    "admin_site_stats": build_site_stats,
    "admin_users": build_users,
    "admin_inventory": build_inventory,
    "admin_payments": build_payments,
    "admin_revenue_year": build_revenue_year,
    "admin_revenue_quarter": build_revenue_quarter,
    "admin_accounting": build_accounting,
    "admin_ai_usage": build_ai_usage,
}
