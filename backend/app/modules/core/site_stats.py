"""Site stats for the admin surfaces (admin lane, owner
2026-11-06 23:14): the numbers the god + moderator_admin Home
widgets show, the daily snapshot the day-over-day deltas read,
and the fact bag the Admin Reports datasets are built from.

Two kinds of facts, kept honest about which is which:

- DERIVED facts are computed from timestamps at read time —
  exact for any day, forever: new accounts, new paid accounts,
  tools logged (the acquisition ledger's created_at), ticket /
  board / flag counts as they stand right now.
- STATE facts describe what the site IS (users per tier, free
  vs paying, MRR). They cannot be reconstructed for a past day
  — tier grants and plan changes leave no timestamped history —
  so the jobs service snapshots them once a day into
  site_stats_snapshots, and a delta is always "now vs the
  latest snapshot from before today". On day one there IS no
  baseline: the delta reads null and the surfaces say so,
  rather than inventing a yesterday.

Money: MRR is the monthly-equivalent of every PAYING
subscription — a subscription row on a paid plan with status
"active" (grants and trials are separate machinery and pay
nothing; the checkout placeholder rows carry status "none" and
grant nothing). Prices are the operator's landing prices (the
same figures the public page quotes): monthly plans at the
monthly price; a subscription whose first period spans more
than 60 days is an annual plan and counts at yearly / 12.
Business prices exist only when the operator sets them — an
unpriced business subscription still counts as a paying
ACCOUNT, it just contributes nothing to MRR until it has a
price (checkout could not have sold it unpriced).
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.billing import entitlements
from app.modules.core import models, tiers

MRR_QUANT = Decimal("0.01")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """A row timestamp as an aware UTC datetime: Postgres hands
    back aware values, SQLite naive ones — normalize before
    comparing against _now() so both dialects read the same."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


# -- state facts -------------------------------------------------------


def users_by_tier(db: Session) -> dict[str, int]:
    """Active accounts per rung, resolved through the tier
    ladder (the fold-in doctrine — the same reading the
    fan-outs use). Deactivated accounts are not members and
    don't count."""
    counts = {rung: 0 for rung in tiers.TIERS}
    for user in db.scalars(
        select(models.User).where(models.User.is_active.is_(True))
    ).all():
        counts[tiers.resolved_tier(user)] += 1
    return counts


def _paid_plan_keys(db: Session) -> set[str]:
    return {
        plan.plan_key for plan in entitlements.list_plans(db) if plan.is_paid
    }


# Member types (admin polish lane, owner 2026-11-07): the four
# kinds of member the owner named for the Site Overview report
# and the Site Stats widget — mechanic, shop, insurance, agent.
# The first three are account groups as the site knows them.
# "Agent" is REGISTERED agents only (owner correction,
# 2026-11-07): an account holding a registered agent identity
# — its own agent profile, or a claimed company representation
# (the platform's registered-agent records; the same identity
# dealers.warranty.registered_agents speaks for). Dealer-group
# membership alone does not make an agent, and private
# user-made agent records never count: a record in one user's
# own book is a contact, not a member. An account holding
# several types counts in EACH — the rows describe kinds of
# membership, not a partition, so they can add up past the
# member total.
MEMBER_TYPE_KEYS = ("mechanic", "shop", "insurance", "agent")

_TYPE_GROUPS = {
    "mechanic": "mechanic_technician",
    "shop": "shop_company",
    "insurance": "insurance",
}


def _agent_user_ids(db: Session) -> set:
    """Accounts holding a REGISTERED agent identity: their own
    agent profile (dealer_agent_profiles), or a claimed company
    representation (dealer_company_representations). Private
    user-made agent records are never read here — not even a
    record linked to an account: the record stays one user's
    book entry, and this count is of registered agents."""
    from app.modules.dealers import models as dealer_models

    ids = set(
        db.scalars(select(dealer_models.AgentProfile.user_id)).all()
    )
    ids.update(
        db.scalars(
            select(dealer_models.CompanyRepresentation.agent_user_id)
        ).all()
    )
    return ids


def users_by_member_type(db: Session) -> dict[str, int]:
    """Active accounts per member type (see MEMBER_TYPE_KEYS).
    Same population as users_by_tier — active accounts only."""
    agent_ids = _agent_user_ids(db)
    counts = {key: 0 for key in MEMBER_TYPE_KEYS}
    for user in db.scalars(
        select(models.User).where(models.User.is_active.is_(True))
    ).all():
        groups = set(user.account_types or [])
        for key, group in _TYPE_GROUPS.items():
            if group in groups:
                counts[key] += 1
        if user.id in agent_ids:
            counts["agent"] += 1
    return counts


def paying_by_plan(db: Session) -> list[dict]:
    """Paying subscriptions broken down by payment category:
    one entry per PAID plan in the catalog (catalog order),
    split monthly vs annual by the same first-period reading
    monthly_equivalent uses. Plans nobody pays on still appear
    (with zeros) so the surfaces can offer a toggle per plan."""
    rows = paying_subscriptions(db)
    out = []
    for plan in entitlements.list_plans(db):
        if not plan.is_paid:
            continue
        mine = [row for row in rows if row.plan_key == plan.plan_key]
        annual = len([row for row in mine if _is_annual(row)])
        out.append(
            {
                "plan_key": plan.plan_key,
                "name": plan.name,
                "monthly": len(mine) - annual,
                "annual": annual,
                "total": len(mine),
            }
        )
    return out


def paying_subscriptions(db: Session) -> list:
    """The subscription rows that represent money recurring:
    a paid plan, status active. See the module docstring for
    the exact rule and why grants/trials/placeholders are out."""
    paid = _paid_plan_keys(db)
    if not paid:
        return []
    from app.modules.billing import models as billing_models

    return list(
        db.scalars(
            select(billing_models.Subscription).where(
                billing_models.Subscription.plan_key.in_(paid),
                billing_models.Subscription.status == "active",
            )
        ).all()
    )


def _price(db: Session, key: str) -> Decimal | None:
    """An operator price (a landing-config string) as money;
    unset or unparseable reads as None — no price, honestly."""
    from app.modules.core import landing

    raw = landing.landing_config(db).get(key) or ""
    try:
        value = Decimal(str(raw).strip())
    except Exception:  # noqa: BLE001 — a display string, not data
        return None
    return value if value > 0 else None


def _is_annual(row) -> bool:
    """Annual-plan reading of one subscription row: its FIRST
    period (creation → first period end) spans more than 60
    days and the row has never been re-synced since (a renewal
    sync rewrites updated_at, after which the span from
    creation measures many periods and says nothing). A row
    that fails either test reads as monthly — the conservative
    direction (it can only overstate MRR toward the monthly
    price the plan also sells at)."""
    created = row.created_at
    end = row.current_period_end
    if created is None or end is None:
        return False
    if row.updated_at is not None and row.updated_at != created:
        return False
    return (end - created) > timedelta(days=60)


def monthly_equivalent(db: Session, row) -> Decimal:
    """One paying subscription's monthly-equivalent price."""
    if row.plan_key == "pro":
        monthly = _price(db, "pro_monthly_price")
        if _is_annual(row):
            yearly = _price(db, "pro_yearly_price")
            if yearly is not None:
                return (yearly / Decimal(12)).quantize(MRR_QUANT)
        return monthly or Decimal("0")
    if row.plan_key == "business":
        monthly = _price(db, "business_monthly_price")
        if monthly is None:
            return Decimal("0")
        if _is_annual(row):
            yearly = _price(db, "business_yearly_price")
            if yearly is not None:
                return (yearly / Decimal(12)).quantize(MRR_QUANT)
        return monthly
    return Decimal("0")


def mrr(db: Session) -> Decimal:
    total = sum(
        (monthly_equivalent(db, row) for row in paying_subscriptions(db)),
        Decimal("0"),
    )
    return total.quantize(MRR_QUANT)


def tools_total(db: Session) -> int:
    """Every top-level item on the site: tools (a set counts
    once, attached pieces ride with it — the inventory stats
    contract) plus batteries."""
    from app.modules.inventory import models as inventory_models

    tools = db.scalar(
        select(func.count(inventory_models.Tool.id)).where(
            inventory_models.Tool.attached_to_set_id.is_(None)
        )
    )
    batteries = db.scalar(select(func.count(inventory_models.Battery.id)))
    return int(tools or 0) + int(batteries or 0)


# -- derived facts -----------------------------------------------------


def _count_between(db: Session, column, day: date) -> int:
    start, end = _day_bounds(day)
    return int(
        db.scalar(
            select(func.count()).where(column >= start, column < end)
        )
        or 0
    )


def new_users_on(db: Session, day: date) -> int:
    return _count_between(db, models.User.created_at, day)


def new_paid_on(db: Session, day: date) -> int:
    """New PAYING accounts on a day: subscription rows created
    that day on a paid plan (any status but the "none"
    placeholder — a checkout that produced a row with a real
    status is a paid account arriving)."""
    paid = _paid_plan_keys(db)
    if not paid:
        return 0
    from app.modules.billing import models as billing_models

    start, end = _day_bounds(day)
    return int(
        db.scalar(
            select(func.count(billing_models.Subscription.id)).where(
                billing_models.Subscription.plan_key.in_(paid),
                billing_models.Subscription.status != "none",
                billing_models.Subscription.created_at >= start,
                billing_models.Subscription.created_at < end,
            )
        )
        or 0
    )


def tools_logged_on(db: Session, day: date) -> int:
    """Tools logged on a day: acquisition-ledger rows written
    that day (the ledger is the honest record of an item being
    entered — quantity changes write rows too, so the count is
    acquisition EVENTS, the closest truth to "logged")."""
    from app.modules.inventory import models as inventory_models

    return _count_between(db, inventory_models.AcquisitionRecord.created_at, day)


# -- the fact bag + the snapshot ----------------------------------------


def current_facts(db: Session, day: date | None = None) -> dict:
    """The whole fact bag for `day` (default today, UTC): the
    state facts as they stand NOW plus the day's derived
    counts. This is what the snapshot writer stores and what
    the widget payload reads for its "now" side."""
    day = day or _now().date()
    by_tier = users_by_tier(db)
    paying = paying_subscriptions(db)
    return {
        "day": day.isoformat(),
        "users_total": sum(by_tier.values()),
        "users_by_tier": by_tier,
        "users_by_type": users_by_member_type(db),
        "paying_by_plan": paying_by_plan(db),
        "free_users": sum(by_tier.values()) - len(paying),
        "paying_users": len(paying),
        "mrr": str(mrr(db)),
        "tools_total": tools_total(db),
        "new_users": new_users_on(db, day),
        "new_paid": new_paid_on(db, day),
        "tools_logged": tools_logged_on(db, day),
    }


def snapshot_day(db: Session, day: date | None = None) -> models.SiteStatsSnapshot:
    """Write (or refresh) one day's snapshot row. Idempotent —
    the daily job re-running corrects the day instead of
    duplicating it."""
    day = day or _now().date()
    facts = current_facts(db, day)
    row = db.scalars(
        select(models.SiteStatsSnapshot).where(
            models.SiteStatsSnapshot.day == day
        )
    ).first()
    if row is None:
        row = models.SiteStatsSnapshot(day=day, payload=facts)
        db.add(row)
    else:
        row.payload = facts
    db.commit()
    db.refresh(row)
    return row


def run_daily_snapshot(db: Session) -> str:
    """The jobs-service entry: refresh TODAY's snapshot (so
    the day's row tracks the day as it unfolds) — yesterday's
    row, last refreshed during yesterday, is the delta
    baseline. One run per day is the cadence; extra runs are
    harmless refreshes."""
    row = snapshot_day(db)
    return f"site stats snapshot for {row.day.isoformat()} written"


def latest_snapshot_before(db: Session, day: date) -> models.SiteStatsSnapshot | None:
    return db.scalars(
        select(models.SiteStatsSnapshot)
        .where(models.SiteStatsSnapshot.day < day)
        .order_by(models.SiteStatsSnapshot.day.desc())
        .limit(1)
    ).first()


# -- the admin Home widgets payload --------------------------------------


def _tickets_block(db: Session) -> dict:
    from app.modules.support import models as support_models

    tickets = list(db.scalars(select(support_models.SupportTicket)).all())
    open_rows = [row for row in tickets if row.status != "closed"]
    unanswered = 0
    for row in open_rows:
        last_kind = db.scalar(
            select(support_models.SupportMessage.author_kind)
            .where(support_models.SupportMessage.ticket_id == row.id)
            .order_by(
                support_models.SupportMessage.created_at.desc(),
                support_models.SupportMessage.id.desc(),
            )
            .limit(1)
        )
        # The ball is in the team's court when the newest word
        # is the member's — or when nobody has written at all.
        if last_kind in (None, "user"):
            unanswered += 1
    return {
        "open": len(open_rows),
        "closed": len(tickets) - len(open_rows),
        "unanswered": unanswered,
        "total": len(tickets),
    }


def _board_block(db: Session, board: str) -> dict:
    from app.modules.feedback import models as feedback_models

    week_ago = _now() - timedelta(days=7)
    rows = list(
        db.scalars(
            select(feedback_models.FeedbackPost).where(
                feedback_models.FeedbackPost.board == board
            )
        ).all()
    )
    live = [row for row in rows if not row.visibility.startswith("removed")]
    open_rows = [
        row for row in live if row.status not in ("done", "declined")
    ]
    top = None
    if live:
        counts = dict(
            db.execute(
                select(
                    feedback_models.FeedbackVote.post_id,
                    func.count(feedback_models.FeedbackVote.id),
                ).group_by(feedback_models.FeedbackVote.post_id)
            ).all()
        )
        best = max(live, key=lambda row: counts.get(row.id, 0))
        top = {
            "title": best.title,
            "votes": int(counts.get(best.id, 0)),
            "href": f"/feedback/post/{best.id}",
        }
    return {
        "total": len(live),
        "open": len(open_rows),
        "new_week": len(
            [
                row
                for row in live
                if row.created_at is not None and _aware(row.created_at) >= week_ago
            ]
        ),
        "done": len([row for row in live if row.status == "done"]),
        "held": len([row for row in rows if row.visibility == "held"]),
        "top": top,
    }


def _forum_moderator_block(db: Session) -> dict:
    from app.modules.feedback import models as feedback_models
    from app.modules.forum import models as forum_models

    forum_flags = list(
        db.scalars(
            select(forum_models.ForumReport)
            .where(forum_models.ForumReport.status == "open")
            .order_by(forum_models.ForumReport.created_at.desc())
        ).all()
    )
    feedback_flags = list(
        db.scalars(
            select(feedback_models.FeedbackReport)
            .where(feedback_models.FeedbackReport.status == "open")
            .order_by(feedback_models.FeedbackReport.created_at.desc())
        ).all()
    )
    flagged: list[dict] = []
    for row in forum_flags[:5]:
        post = db.get(forum_models.ForumPost, row.post_id)
        thread = db.get(forum_models.ForumThread, row.thread_id)
        flagged.append(
            {
                "surface": "forum",
                "title": thread.title if thread is not None else "",
                "excerpt": (post.body[:160] if post is not None else ""),
                "reason": row.reason,
                "href": f"/forum/thread/{row.thread_id}",
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    for row in feedback_flags[:5]:
        # The door is always the parent post's page: for a post
        # target that's the target itself; for a comment target
        # it's the comment's post.
        if row.target_kind == "post":
            target_post = db.get(feedback_models.FeedbackPost, row.target_id)
            excerpt = (target_post.body[:160] if target_post is not None else "")
        else:
            comment = db.get(feedback_models.FeedbackComment, row.target_id)
            target_post = (
                db.get(feedback_models.FeedbackPost, comment.post_id)
                if comment is not None
                else None
            )
            excerpt = (comment.body[:160] if comment is not None else "")
        flagged.append(
            {
                "surface": "feedback",
                "title": target_post.title if target_post is not None else "",
                "excerpt": excerpt,
                "reason": row.reason,
                "href": (
                    f"/feedback/post/{target_post.id}"
                    if target_post is not None
                    else "/feedback/bugs"
                ),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    flagged.sort(key=lambda item: item["created_at"] or "", reverse=True)

    today_start, today_end = _day_bounds(_now().date())
    new_posts = int(
        db.scalar(
            select(func.count(forum_models.ForumPost.id)).where(
                forum_models.ForumPost.created_at >= today_start,
                forum_models.ForumPost.created_at < today_end,
            )
        )
        or 0
    ) + int(
        db.scalar(
            select(func.count(feedback_models.FeedbackPost.id)).where(
                feedback_models.FeedbackPost.created_at >= today_start,
                feedback_models.FeedbackPost.created_at < today_end,
            )
        )
        or 0
    )

    reply_counts = dict(
        db.execute(
            select(
                forum_models.ForumPost.thread_id,
                func.count(forum_models.ForumPost.id),
            ).group_by(forum_models.ForumPost.thread_id)
        ).all()
    )
    threads = list(db.scalars(select(forum_models.ForumThread)).all())
    threads.sort(key=lambda th: reply_counts.get(th.id, 0), reverse=True)
    top_threads = [
        {
            "title": th.title,
            "replies": max(int(reply_counts.get(th.id, 0)) - 1, 0),
            "href": f"/forum/thread/{th.id}",
        }
        for th in threads[:3]
        if reply_counts.get(th.id, 0) > 1
    ]

    held_forum = int(
        db.scalar(
            select(func.count(forum_models.ForumPost.id)).where(
                forum_models.ForumPost.status == "held"
            )
        )
        or 0
    )
    held_feedback = int(
        db.scalar(
            select(func.count(feedback_models.FeedbackPost.id)).where(
                feedback_models.FeedbackPost.visibility == "held"
            )
        )
        or 0
    ) + int(
        db.scalar(
            select(func.count(feedback_models.FeedbackComment.id)).where(
                feedback_models.FeedbackComment.visibility == "held"
            )
        )
        or 0
    )
    return {
        "open_flags": len(forum_flags) + len(feedback_flags),
        "open_flags_forum": len(forum_flags),
        "open_flags_feedback": len(feedback_flags),
        "held": held_forum + held_feedback,
        "held_forum": held_forum,
        "held_feedback": held_feedback,
        "new_posts_today": new_posts,
        "flagged": flagged[:5],
        "top_threads": top_threads,
    }


def _site_block(db: Session) -> dict:
    today = _now().date()
    now_facts = current_facts(db, today)
    baseline = latest_snapshot_before(db, today)
    base_payload = baseline.payload if baseline is not None else None
    tier_deltas = None
    paying_delta = None
    type_deltas = None
    plan_deltas = None
    if base_payload is not None:
        base_tiers = base_payload.get("users_by_tier") or {}
        tier_deltas = {
            rung: now_facts["users_by_tier"].get(rung, 0)
            - int(base_tiers.get(rung, 0))
            for rung in tiers.TIERS
        }
        paying_delta = now_facts["paying_users"] - int(
            base_payload.get("paying_users", 0)
        )
        # The member-type and per-plan dimensions entered the
        # snapshot with the admin polish lane: a baseline written
        # before that has neither key, and the honest reading is
        # "no baseline for these rows" (null), never a backfill.
        base_types = base_payload.get("users_by_type")
        if isinstance(base_types, dict):
            type_deltas = {
                key: now_facts["users_by_type"].get(key, 0)
                - int(base_types.get(key, 0))
                for key in MEMBER_TYPE_KEYS
            }
        base_plans = base_payload.get("paying_by_plan")
        if isinstance(base_plans, list):
            base_by_key = {
                row.get("plan_key"): row
                for row in base_plans
                if isinstance(row, dict)
            }
            plan_deltas = {
                row["plan_key"]: {
                    part: row[part]
                    - int((base_by_key.get(row["plan_key"]) or {}).get(part, 0))
                    for part in ("monthly", "annual", "total")
                }
                for row in now_facts["paying_by_plan"]
            }
    return {
        **now_facts,
        "tier_deltas": tier_deltas,
        "paying_delta": paying_delta,
        "type_deltas": type_deltas,
        "plan_deltas": plan_deltas,
        "baseline_day": baseline.day.isoformat() if baseline is not None else None,
    }


def home_widgets_payload(db: Session) -> dict:
    """The five admin Home widgets' whole read, in one payload
    (the widgets' per-stat toggles are the client's layout
    settings — the endpoint itself is tier-gated, so the full
    bag travels only to admin seats)."""
    return {
        "tickets": _tickets_block(db),
        "bug_reports": _board_block(db, "bug"),
        "feature_requests": _board_block(db, "feature"),
        "forum_moderator": _forum_moderator_block(db),
        "site": _site_block(db),
    }
