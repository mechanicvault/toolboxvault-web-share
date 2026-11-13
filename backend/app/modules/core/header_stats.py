"""Home header-stats catalog (Lane 3, owner design 2026-11-10).

The Home page header carries the user's key numbers (the stats
widget's content, moved into the header). WHICH stats a user may
pick is a reach question, so the catalog is enumerated HERE,
server-side, from the caller's effective reach — the picker never
lists a stat outside the caller's reach (a staff stat like "New
members today" does not exist as far as a mechanic's picker is
concerned).

Each entry declares only its REACH: the feature module that owns
the number (gated by module_control.effective_for_user — tier,
group, and per-user layers all apply), the account groups the
number belongs to (None = group-agnostic), and whether it is a
staff stat (god / moderator_admin / operator seats — the same
seat rule as the admin Home widgets and require_user_manager).
Labels, links, and value reads live in the frontend catalog
(frontend/src/modules/core/homeHeaderStats.tsx), which mirrors
this table key for key; a key the server does not return is never
rendered or offered, whatever the client thinks of it.

Values: almost every stat's number is read by the client from the
owning module's own endpoint (the same read the module's pages
use — no forked numbers). The two staff stats with no module
endpoint of their own are computed here and returned as `values`:
new members today and AI actions today, both counted on the
America/Chicago calendar day (the site's home timezone), not UTC.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser
from app.modules.billing import models as billing_models
from app.modules.core import models, module_control

CHICAGO = ZoneInfo("America/Chicago")

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"
INSURANCE = "insurance"
ALL_GROUPS = (MECHANIC, SHOP, DEALER, INSURANCE)

# (key, module, groups, staff) — catalog order is the picker's
# order within each module group and the defaults' fill order.
STAT_CATALOG: tuple[tuple[str, str | None, tuple[str, ...] | None, bool], ...] = (
    # Inventory (seeded from the retired overview registry).
    ("inventory.total_items", "inventory", (MECHANIC,), False),
    ("inventory.total_market_value", "inventory", (MECHANIC,), False),
    ("inventory.total_quantity", "inventory", (MECHANIC,), False),
    ("inventory.total_replacement_cost", "inventory", (MECHANIC,), False),
    ("inventory.warranties_expiring_soon", "inventory", (MECHANIC,), False),
    ("inventory.warranties_expired", "inventory", (MECHANIC,), False),
    ("inventory.category_count", "inventory", (MECHANIC,), False),
    # Borrowing.
    ("borrowing.checked_out", "borrowing", (MECHANIC, SHOP), False),
    ("borrowing.borrowed_by_me", "borrowing", (MECHANIC, SHOP), False),
    # Warranty & repair claims.
    ("claims.open_claims", "claims", (MECHANIC, SHOP), False),
    # Maintenance.
    ("maintenance.maintenance_due", "maintenance", (MECHANIC, SHOP), False),
    ("maintenance.out_of_service", "maintenance", (MECHANIC, SHOP), False),
    # Disaster claims.
    ("disaster_claims.open_claims", "disaster_claims", (MECHANIC, SHOP), False),
    # Parts (parked module — the gate resolves it away until it returns).
    ("parts.used_parts", "parts", (MECHANIC, SHOP), False),
    # Truck accounts (the module's own status-summary reading: the
    # two sides are never summed; see the frontend read).
    ("truck_accounts.open_accounts", "truck_accounts", (MECHANIC, SHOP, DEALER), False),
    ("truck_accounts.total_owed", "truck_accounts", (MECHANIC, SHOP, DEALER), False),
    ("truck_accounts.payments_this_week", "truck_accounts", (MECHANIC, SHOP, DEALER), False),
    # Dealers: the directory page's own header facts + portal stats.
    ("dealers.directory", "dealers", ALL_GROUPS, False),
    ("dealers.my_companies", "dealers", ALL_GROUPS, False),
    ("dealers.my_agents", "dealers", ALL_GROUPS, False),
    ("dealers.preferred_by", "dealers", (DEALER,), False),
    ("dealers.companies_represented", "dealers", (DEALER,), False),
    ("dealers.profile_visibility", "dealers", (DEALER,), False),
    # Flyers: sources with a flyer up this week (the feed's count).
    ("flyers.this_week", "flyers", (MECHANIC, SHOP, DEALER), False),
    # Marketplace / wishlist / messaging (parked modules resolve away).
    ("marketplace.active_listings", "marketplace", None, False),
    ("wishlist.items", "wishlist", (MECHANIC, SHOP), False),
    ("messaging.unread", "messaging", None, False),
    # Support: the caller's own open tickets (the support stats read).
    ("support.open_tickets", "support", None, False),
    # Feedback: the caller's own board posts.
    ("feedback.my_posts", "feedback", None, False),
    # Downloads (always-on infra, no feature module; prints has one).
    ("downloads.documents", None, None, False),
    ("downloads.wallpapers", None, None, False),
    ("downloads.total_downloads", None, None, False),
    ("prints.listings", "prints", None, False),
    ("prints.downloads", "prints", None, False),
    ("prints.my_uploads", "prints", None, False),
    ("prints.my_downloads", "prints", None, False),
    # Account: the plan's active-item count (the billing read).
    ("account.plan_items", None, None, False),
    # Staff stats — god / moderator_admin / operator seats only.
    ("admin.members_total", None, None, True),
    ("admin.new_members_today", None, None, True),
    ("admin.new_paid_today", None, None, True),
    ("admin.paying_members", None, None, True),
    ("admin.mrr", None, None, True),
    ("admin.tools_total", None, None, True),
    ("admin.tools_logged_today", None, None, True),
    ("admin.ai_actions_today", None, None, True),
    ("admin.open_tickets", None, None, True),
)

CATALOG_KEYS: tuple[str, ...] = tuple(entry[0] for entry in STAT_CATALOG)


def is_staff(user: CurrentUser) -> bool:
    """The admin seat rule (require_user_manager, mirrored)."""
    return bool(user.is_operator or user.tier in ("god", "moderator_admin"))


def available_stat_keys(db: Session, user: CurrentUser) -> list[str]:
    """The catalog keys inside THIS caller's effective reach, in
    catalog order. God bypasses every layer (module_control's own
    doctrine: god sees and can use all modules). The downloads
    rung carries no account types, so group-gated stats stay out
    and its tier-lit modules (prints, support, feedback) plus the
    group-agnostic infra stats (downloads, account) stay in."""
    groups = tuple(user.account_types or ())
    staff = is_staff(user)
    god = user.tier == "god"
    available: list[str] = []
    for key, module_id, stat_groups, staff_only in STAT_CATALOG:
        if staff_only and not staff:
            continue
        if god:
            available.append(key)
            continue
        if stat_groups is not None and not (set(stat_groups) & set(groups)):
            continue
        if module_id is not None and not module_control.effective_for_user(
            db,
            module_id,
            groups,
            user_id=user.id,
            tier=user.tier,
            beta_tester=user.beta_tester,
        ):
            continue
        available.append(key)
    return available


def _chicago_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """[start, end) of the current America/Chicago calendar day,
    as UTC-aware datetimes (User.created_at / AiUsage.created_at
    are stored UTC-aware)."""
    current = now or datetime.now(timezone.utc)
    local = current.astimezone(CHICAGO)
    start_local = datetime.combine(local.date(), time.min, tzinfo=CHICAGO)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def new_members_today(db: Session, now: datetime | None = None) -> int:
    """Users created on the current America/Chicago calendar day."""
    start, end = _chicago_day_bounds(now)
    rows = db.scalars(select(models.User.created_at)).all()
    return sum(1 for created in rows if start <= _aware(created) < end)


def ai_actions_today(db: Session, now: datetime | None = None) -> int:
    """AI actions (ai_usage rows) on the current America/Chicago
    calendar day — the admin AI stats' daily figure. Python-side
    filter, like site_stats: the test dialect stores naive
    timestamps, so SQL bounds against aware values mis-compare."""
    start, end = _chicago_day_bounds(now)
    rows = db.scalars(select(billing_models.AiUsage.created_at)).all()
    return sum(1 for created in rows if start <= _aware(created) < end)


def header_stats_payload(db: Session, user: CurrentUser) -> dict:
    """GET /api/core/header-stats: the caller's reachable catalog
    keys, plus the server-computed values for the staff stats that
    have no module endpoint of their own (staff callers only —
    the keys are absent entirely for everyone else)."""
    payload: dict = {"available": available_stat_keys(db, user)}
    if is_staff(user):
        payload["values"] = {
            "admin.new_members_today": new_members_today(db),
            "admin.ai_actions_today": ai_actions_today(db),
        }
    return payload


__all__ = [
    "CATALOG_KEYS",
    "STAT_CATALOG",
    "ai_actions_today",
    "available_stat_keys",
    "header_stats_payload",
    "is_staff",
    "new_members_today",
]
