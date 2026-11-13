"""Site pulse (sweep lane D4, owner idea 5): the operator's
morning glance — signups, downloads activity, new 3D print
listings, and AI usage/cost on ONE aggregate read, every number
computed from data the system already keeps and every number
labelled with its window.

Sources (no new tables, no new telemetry):
- Signups: `users.created_at` (windows) + the tier split from
  core/site_stats.users_by_tier (ACTIVE accounts by RESOLVED
  rung, the same reading the Admin Reports site-stats dataset
  uses — a state fact, labelled as "now", never windowed,
  because an account's rung can change after signup).
- Downloads activity: `download_events` rows (the dated
  download record the Downloads section already writes; the
  per-file `download_count` counters carry no dates, so the
  events table is the only honest windowed source — and its
  all-time count IS the total).
- 3D prints: `print_files.created_at` for new listings, with
  the total counting LIVE listings only (status = "live") —
  removed listings are not on the shelf and don't count.
- AI: `ai_usage` rows (the metering table the Admin Reports
  AI Usage dataset reads). "Calls" is the recorded provider
  round-trips (the `calls` column summed); "cost" is the
  AI-wallet credits charged (`credits_charged` summed) — the
  only cost the system records. The per-purpose split groups
  the last 30 days by the recorded `action`.
- Attention strip: support tickets not yet closed
  (`support_tickets.status` in open / under_review) and
  feature announcements actually sent
  (`feature_announcements.status` = "sent").

Windows are UTC calendar windows ending today: "today" is
today since 00:00 UTC, "last 7 days" is today plus the six
days before it, "last 30 days" likewise. All counts are
indexed `func.count` / aggregate queries — no per-row scans.
"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.billing import models as billing_models
from app.modules.core import models, site_stats
from app.modules.downloads import models as downloads_models
from app.modules.prints import models as prints_models
from app.modules.support import models as support_models

# The ai_service PRICE_KEYS vocabulary, labelled the way the
# Admin Reports AI Usage dataset labels it.
AI_ACTION_LABELS = {
    "lookup": "Catalog lookup",
    "identify": "Identify (text + photo)",
    "manual_lookup": "Manual lookup",
    "report_summary": "Report summary",
    "drawer_lookup": "Drawer lookup",
}


def _windows(now: datetime) -> dict[str, tuple[datetime, datetime]]:
    """UTC calendar windows: [start, tomorrow 00:00 UTC)."""
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end = today_start + timedelta(days=1)
    return {
        "today": (today_start, end),
        "last_7_days": (today_start - timedelta(days=6), end),
        "last_30_days": (today_start - timedelta(days=29), end),
    }


def _count_between(db: Session, column, window: tuple[datetime, datetime]) -> int:
    start, end = window
    return int(
        db.scalar(
            select(func.count()).where(column >= start, column < end)
        )
        or 0
    )


def _count_total(db: Session, model) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _ai_window(db: Session, window: tuple[datetime, datetime]) -> dict:
    start, end = window
    row = db.execute(
        select(
            func.count(billing_models.AiUsage.id),
            func.coalesce(func.sum(billing_models.AiUsage.calls), 0),
            func.coalesce(func.sum(billing_models.AiUsage.credits_charged), 0),
            func.coalesce(func.sum(billing_models.AiUsage.tokens_in), 0),
            func.coalesce(func.sum(billing_models.AiUsage.tokens_out), 0),
        ).where(
            billing_models.AiUsage.created_at >= start,
            billing_models.AiUsage.created_at < end,
        )
    ).one()
    return {
        "actions": int(row[0] or 0),
        "calls": int(row[1] or 0),
        "credits_charged": int(row[2] or 0),
        "tokens_in": int(row[3] or 0),
        "tokens_out": int(row[4] or 0),
    }


def _ai_by_action(db: Session, window: tuple[datetime, datetime]) -> list[dict]:
    start, end = window
    rows = db.execute(
        select(
            billing_models.AiUsage.action,
            func.count(billing_models.AiUsage.id),
            func.coalesce(func.sum(billing_models.AiUsage.calls), 0),
            func.coalesce(func.sum(billing_models.AiUsage.credits_charged), 0),
        )
        .where(
            billing_models.AiUsage.created_at >= start,
            billing_models.AiUsage.created_at < end,
        )
        .group_by(billing_models.AiUsage.action)
    ).all()
    by_key = {row[0]: row for row in rows}
    ordered = [key for key in AI_ACTION_LABELS if key in by_key] + sorted(
        key for key in by_key if key not in AI_ACTION_LABELS
    )
    return [
        {
            "action": key,
            "label": AI_ACTION_LABELS.get(key, key),
            "actions": int(by_key[key][1] or 0),
            "calls": int(by_key[key][2] or 0),
            "credits_charged": int(by_key[key][3] or 0),
        }
        for key in ordered
    ]


def pulse_payload(db: Session, now: datetime | None = None) -> dict:
    """The whole morning glance in one bag. `now` is injectable
    so the window math is testable without clock games."""
    now = now or datetime.now(timezone.utc)
    windows = _windows(now)

    signups = {
        "today": _count_between(db, models.User.created_at, windows["today"]),
        "last_7_days": _count_between(
            db, models.User.created_at, windows["last_7_days"]
        ),
        "total": _count_total(db, models.User),
        # State fact, labelled as now: active accounts per
        # resolved rung (site_stats' reading).
        "by_tier_now": site_stats.users_by_tier(db),
    }

    downloads = {
        "today": _count_between(
            db, downloads_models.DownloadEvent.created_at, windows["today"]
        ),
        "last_7_days": _count_between(
            db,
            downloads_models.DownloadEvent.created_at,
            windows["last_7_days"],
        ),
        "total": _count_total(db, downloads_models.DownloadEvent),
    }

    live = prints_models.PrintFile.status == "live"
    prints = {
        "today": int(
            db.scalar(
                select(func.count(prints_models.PrintFile.id)).where(
                    live,
                    prints_models.PrintFile.created_at >= windows["today"][0],
                    prints_models.PrintFile.created_at < windows["today"][1],
                )
            )
            or 0
        ),
        "last_7_days": int(
            db.scalar(
                select(func.count(prints_models.PrintFile.id)).where(
                    live,
                    prints_models.PrintFile.created_at
                    >= windows["last_7_days"][0],
                    prints_models.PrintFile.created_at
                    < windows["last_7_days"][1],
                )
            )
            or 0
        ),
        "total_live": int(
            db.scalar(
                select(func.count(prints_models.PrintFile.id)).where(live)
            )
            or 0
        ),
    }

    ai = {
        "today": _ai_window(db, windows["today"]),
        "last_7_days": _ai_window(db, windows["last_7_days"]),
        "last_30_days": _ai_window(db, windows["last_30_days"]),
        "by_action_last_30_days": _ai_by_action(db, windows["last_30_days"]),
    }

    attention = {
        "support_tickets_waiting": int(
            db.scalar(
                select(func.count(support_models.SupportTicket.id)).where(
                    support_models.SupportTicket.status.in_(
                        ["open", "under_review"]
                    )
                )
            )
            or 0
        ),
        "announcements_sent_total": int(
            db.scalar(
                select(func.count(models.FeatureAnnouncement.id)).where(
                    models.FeatureAnnouncement.status == "sent"
                )
            )
            or 0
        ),
    }

    return {
        "generated_at": now.isoformat(),
        "signups": signups,
        "downloads": downloads,
        "prints": prints,
        "ai": ai,
        "attention": attention,
    }
