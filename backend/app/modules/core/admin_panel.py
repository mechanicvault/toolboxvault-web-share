"""Admin panel widgets: Admin overview, Site scoreboard and
System health, as Home widgets for admin seats. ONE aggregate
read behind GET /api/admin/panel (require_user_manager).

Every number comes from data the system already keeps, and
every source is named where it is read. Windowed counts use
business-day calendar windows ("today" is the America/Chicago
day since its midnight, "last 7 days" is today plus the six
before it, "last 30 days" likewise): signups from
users.created_at, cancellations from
subscription_status_changes read through
entitlements.is_cancellation_change (the Accounting report's
one definition), and so on per source.

Health checks run at read time against the real systems (a
timed SELECT 1, a capped storage listing, the latest backup
ledger row, the jobs ledger's latest run per job, ...). A
check the system cannot honestly answer reports "unknown" —
never an invented OK. There is NO uptime figure anywhere in
this payload: the site does not measure its own uptime, so the
health summary counts the checks themselves ("x of y systems
normal")."""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.billing import entitlements
from app.modules.billing import models as billing_models
from app.modules.core import models, site_stats
from app.modules.downloads import models as downloads_models
from app.modules.feedback import models as feedback_models
from app.modules.forum import models as forum_models
from app.modules.inventory import models as inventory_models
from app.modules.prints import models as prints_models
from app.modules.support import models as support_models


# -- windows (site_pulse convention, business days) -------------------


def _windows(now: datetime) -> dict[str, tuple[datetime, datetime]]:
    """Business-day windows (America/Chicago, sheet row 119),
    bounds in UTC: today / last 7 / last 30, plus the prior
    7 / prior 30 the overview deltas compare against."""
    from app.core.business_time import business_date, business_day_bounds

    day = business_date(now)

    def start_of(d: date) -> datetime:
        return business_day_bounds(d)[0]

    today_start, end = business_day_bounds(day)
    return {
        "today": (today_start, end),
        "last_7_days": (start_of(day - timedelta(days=6)), end),
        "last_30_days": (start_of(day - timedelta(days=29)), end),
        "prior_7_days": (
            start_of(day - timedelta(days=13)),
            start_of(day - timedelta(days=6)),
        ),
        "prior_30_days": (
            start_of(day - timedelta(days=59)),
            start_of(day - timedelta(days=29)),
        ),
    }


def _count_between(db: Session, column, window: tuple[datetime, datetime]) -> int:
    start, end = window
    return int(
        db.scalar(select(func.count()).where(column >= start, column < end))
        or 0
    )


def _pct_change(current: int, prior: int) -> float | None:
    """Percent change, one decimal; None when there is no
    baseline to divide by (the client prints "new")."""
    if prior == 0:
        return None
    return round((current - prior) / prior * 100, 1)


# -- overview ------------------------------------------------------------


def _signups_series(db: Session, windows) -> list[int]:
    """Signups per business day for the last 30 days, oldest
    first — the overview hero's sparkline. Rows bucket by their
    Chicago calendar date, so a DST week never shifts a day."""
    start = windows["last_30_days"][0]
    end = windows["last_30_days"][1]
    rows = db.scalars(
        select(models.User.created_at).where(
            models.User.created_at >= start, models.User.created_at < end
        )
    ).all()
    series = [0] * 30
    for created in rows:
        aware = created if created.tzinfo is not None else created.replace(
            tzinfo=timezone.utc
        )
        from app.core.business_time import BUSINESS_TZ

        first_day = start.astimezone(BUSINESS_TZ).date()
        series[(aware.astimezone(BUSINESS_TZ).date() - first_day).days] += 1
    return series


def _ai_window(db: Session, window) -> dict:
    start, end = window
    row = db.execute(
        select(
            func.coalesce(func.sum(billing_models.AiUsage.calls), 0),
            func.coalesce(func.sum(billing_models.AiUsage.credits_charged), 0),
        ).where(
            billing_models.AiUsage.created_at >= start,
            billing_models.AiUsage.created_at < end,
        )
    ).one()
    return {"calls": int(row[0] or 0), "credits": int(row[1] or 0)}


def _overview(db: Session, windows, now: datetime) -> dict:
    facts = site_stats.current_facts(db)
    tiles: dict[str, dict] = {}
    for key in ("today", "last_7_days", "last_30_days", "prior_7_days", "prior_30_days"):
        w = windows[key]
        ai = _ai_window(db, w)
        tiles[key] = {
            "downloads": _count_between(
                db, downloads_models.DownloadEvent.created_at, w
            ),
            "tools_logged": _count_between(
                db, inventory_models.AcquisitionRecord.created_at, w
            ),
            "ai_credits": ai["credits"],
            "ai_calls": ai["calls"],
        }
    changes = {}
    for key, prior_key in (
        ("last_7_days", "prior_7_days"),
        ("last_30_days", "prior_30_days"),
    ):
        changes[key] = {
            metric: _pct_change(tiles[key][metric], tiles[prior_key][metric])
            for metric in ("downloads", "tools_logged", "ai_credits")
        }
    bag = site_stats.home_widgets_payload(db)
    tickets = bag["tickets"]
    forum_mod = bag["forum_moderator"]
    bugs = bag["bug_reports"]
    # The sample panel's "high-priority bug": the board's own
    # urgency lever (low | medium | high), open posts only.
    bugs_high = int(
        db.scalar(
            select(func.count(feedback_models.FeedbackPost.id)).where(
                feedback_models.FeedbackPost.board == "bug",
                feedback_models.FeedbackPost.urgency == "high",
                feedback_models.FeedbackPost.status.notin_(["done", "declined"]),
                ~feedback_models.FeedbackPost.visibility.startswith("removed"),
            )
        )
        or 0
    )
    over_24h = int(
        db.scalar(
            select(func.count(support_models.SupportTicket.id)).where(
                support_models.SupportTicket.status.in_(["open", "under_review"]),
                support_models.SupportTicket.created_at
                < now - timedelta(hours=24),
            )
        )
        or 0
    )
    return {
        "users_total": facts["users_total"],
        "paying_users": facts["paying_users"],
        "free_users": facts["free_users"],
        "mrr": str(facts["mrr"]),
        "signups_series_30d": _signups_series(db, windows),
        # Sheet row 50: the overview chart
        # names the exact date under the mouse, so the client
        # needs the series' first day — index i is this date
        # plus i days (the series is UTC days, oldest first).
        "signups_series_start": windows["last_30_days"][0].date().isoformat(),
        "new_last_7_days": _count_between(
            db, models.User.created_at, windows["last_7_days"]
        ),
        "new_prior_7_days": _count_between(
            db, models.User.created_at, windows["prior_7_days"]
        ),
        "new_last_30_days": _count_between(
            db, models.User.created_at, windows["last_30_days"]
        ),
        "tiles": {k: tiles[k] for k in ("today", "last_7_days", "last_30_days")},
        "tile_changes": changes,
        "attention": {
            "tickets_open": tickets["open"],
            "tickets_over_24h": over_24h,
            "flagged_posts": forum_mod["open_flags"],
            "held_posts": forum_mod["held"],
            "bug_reports_open": bugs["open"],
            "bug_reports_high": bugs_high,
        },
    }


# -- scoreboard ------------------------------------------------------------


def _cancellations_between(db: Session, window) -> int:
    """Subscription cancellations in the window, counted with
    the Accounting report's one definition: a recorded
    transition from a live state into a terminal one."""
    start, end = window
    rows = db.execute(
        select(
            billing_models.SubscriptionStatusChange.from_status,
            billing_models.SubscriptionStatusChange.to_status,
        ).where(
            billing_models.SubscriptionStatusChange.created_at >= start,
            billing_models.SubscriptionStatusChange.created_at < end,
        )
    ).all()
    return sum(
        1
        for from_status, to_status in rows
        if entitlements.is_cancellation_change(from_status, to_status)
    )


def _scoreboard(db: Session, windows) -> list[dict]:
    def counts(column) -> dict:
        return {
            "today": _count_between(db, column, windows["today"]),
            "last_7_days": _count_between(db, column, windows["last_7_days"]),
            "last_30_days": _count_between(db, column, windows["last_30_days"]),
            "prior_30_days": _count_between(db, column, windows["prior_30_days"]),
        }

    def paid_counts() -> dict:
        return {
            key: site_stats._new_paid_between(db, *windows[key])
            for key in ("today", "last_7_days", "last_30_days", "prior_30_days")
        }

    def cancellation_counts() -> dict:
        return {
            key: _cancellations_between(db, windows[key])
            for key in ("today", "last_7_days", "last_30_days", "prior_30_days")
        }

    def bug_counts() -> dict:
        out = {}
        for key in ("today", "last_7_days", "last_30_days", "prior_30_days"):
            start, end = windows[key]
            out[key] = int(
                db.scalar(
                    select(func.count(feedback_models.FeedbackPost.id)).where(
                        feedback_models.FeedbackPost.board == "bug",
                        ~feedback_models.FeedbackPost.visibility.startswith(
                            "removed"
                        ),
                        feedback_models.FeedbackPost.created_at >= start,
                        feedback_models.FeedbackPost.created_at < end,
                    )
                )
                or 0
            )
        return out

    def ai_counts() -> dict:
        return {
            key: _ai_window(db, windows[key])["credits"]
            for key in ("today", "last_7_days", "last_30_days", "prior_30_days")
        }

    rows_spec = [
        ("new_users", "count", "up", counts(models.User.created_at)),
        ("new_paid", "count", "up", paid_counts()),
        ("cancellations", "count", "down", cancellation_counts()),
        (
            "tools_logged",
            "count",
            "up",
            counts(inventory_models.AcquisitionRecord.created_at),
        ),
        (
            "downloads",
            "count",
            "up",
            counts(downloads_models.DownloadEvent.created_at),
        ),
        ("prints_uploaded", "count", "up", counts(prints_models.PrintFile.created_at)),
        ("forum_posts", "count", "up", counts(forum_models.ForumPost.created_at)),
        (
            "support_tickets",
            "count",
            "up",
            counts(support_models.SupportTicket.created_at),
        ),
        ("bug_reports", "count", "up", bug_counts()),
        ("ai_credits", "credits", "down", ai_counts()),
    ]
    rows = []
    for key, fmt, good_when, values in rows_spec:
        rows.append(
            {
                "key": key,
                "format": fmt,
                "good_when": good_when,
                "today": values["today"],
                "last_7_days": values["last_7_days"],
                "last_30_days": values["last_30_days"],
                "change_pct": _pct_change(
                    values["last_30_days"], values["prior_30_days"]
                ),
            }
        )
    return rows


# -- health ----------------------------------------------------------------


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "—"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def _check_database(db: Session) -> dict:
    started = time.perf_counter()
    db.execute(text("SELECT 1")).first()
    ms = (time.perf_counter() - started) * 1000
    size = None
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        size = db.scalar(text("SELECT pg_database_size(current_database())"))
        kind = "PostgreSQL"
    elif dialect == "sqlite":
        url = str(db.get_bind().url)
        path = url.split("///", 1)[-1]
        if path and os.path.exists(path):
            size = os.path.getsize(path)
        kind = "SQLite"
    else:
        kind = dialect
    return {
        "key": "database",
        "status": "ok",
        "value": f"{ms:.0f} ms response",
        "detail": f"{kind} · {_fmt_bytes(size)}",
    }


def _check_storage() -> dict:
    try:
        import boto3
        from botocore.config import Config

        from app.core.storage import storage

        # A DEDICATED short-timeout client: the shared client's
        # default retries would hold the whole panel payload
        # hostage when storage is unreachable — the check must
        # answer "unknown" in seconds, never hang the widgets.
        client = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_app_user,
            aws_secret_access_key=settings.minio_app_password,
            config=Config(
                connect_timeout=2,
                read_timeout=3,
                retries={"max_attempts": 1},
            ),
        )
        total = 0
        count = 0
        capped = False
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=storage.bucket):
            for obj in page.get("Contents", []):
                total += int(obj.get("Size", 0))
                count += 1
                if count >= 10000:
                    capped = True
                    break
            if capped:
                break
        detail = f"{count:,} files in storage" + (" (first 10,000 counted)" if capped else "")
        return {
            "key": "storage",
            "status": "ok",
            "value": f"{_fmt_bytes(total)} used",
            "detail": detail,
        }
    except Exception:
        return {
            "key": "storage",
            "status": "unknown",
            "value": "—",
            "detail": "Storage could not be read from here",
        }


def _check_backup(db: Session) -> dict:
    run = db.scalars(
        select(models.BackupRun).order_by(models.BackupRun.started_at.desc())
    ).first()
    if run is None:
        return {
            "key": "backup",
            "status": "check",
            "value": "No runs recorded",
            "detail": "The nightly backup has no ledger rows yet",
        }
    when = run.finished_at or run.started_at
    aware = when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)
    value = f"Finished {aware.strftime('%b %d, %I:%M %p')}"
    detail = _fmt_bytes(run.size_bytes) + (
        " · off-site copy uploaded" if run.uploaded else " · server copy only"
    )
    status = {
        "ok": "ok",
        "local_only": "watch",
        "encryption_not_configured": "watch",
        "failed": "check",
        "running": "watch",
    }.get(run.status, "unknown")
    if run.status == "running":
        value = "A backup run is in progress"
    if run.status == "failed":
        value = f"Last run failed {aware.strftime('%b %d, %I:%M %p')}"
    return {"key": "backup", "status": status, "value": value, "detail": detail}


def _check_email(db: Session, windows) -> dict:
    start, end = windows["last_7_days"]
    rows = db.execute(
        select(models.EmailOutbox.status, func.count(models.EmailOutbox.id))
        .where(
            models.EmailOutbox.created_at >= start,
            models.EmailOutbox.created_at < end,
        )
        .group_by(models.EmailOutbox.status)
    ).all()
    by_status = {status: int(count) for status, count in rows}
    failed = by_status.get("failed", 0)
    if settings.email_provider == "dev":
        logged = by_status.get("logged", 0)
        return {
            "key": "email",
            "status": "watch",
            "value": f"{logged:,} logged · 7 days",
            "detail": "Dev provider — messages are recorded, not delivered",
        }
    sent = by_status.get("sent", 0)
    status = "ok" if failed == 0 else ("watch" if failed <= 3 else "check")
    return {
        "key": "email",
        "status": status,
        "value": f"{sent:,} sent · 7 days",
        "detail": f"{failed} failed" if failed else "No failures in 7 days",
    }


def _check_stripe(db: Session, windows) -> dict:
    if not settings.stripe_secret_key:
        return {
            "key": "stripe",
            "status": "off",
            "value": "Not connected",
            "detail": "Stripe keys are not set on the server",
        }
    start, end = windows["last_7_days"]
    events = int(
        db.scalar(
            select(func.count(billing_models.StripeEvent.id)).where(
                billing_models.StripeEvent.created_at >= start,
                billing_models.StripeEvent.created_at < end,
            )
        )
        or 0
    )
    return {
        "key": "stripe",
        "status": "ok" if events > 0 else "watch",
        "value": f"{events:,} webhook events · 7 days",
        "detail": (
            "Webhooks are being received"
            if events > 0
            else "Connected, but no webhook events in 7 days"
        ),
    }


def _check_ai(db: Session, windows) -> dict:
    ai = _ai_window(db, windows["last_30_days"])
    actions = int(
        db.scalar(
            select(func.count(billing_models.AiUsage.id)).where(
                billing_models.AiUsage.created_at >= windows["last_30_days"][0],
                billing_models.AiUsage.created_at < windows["last_30_days"][1],
            )
        )
        or 0
    )
    return {
        "key": "ai",
        "status": "ok",
        "value": f"{ai['credits']:,} credits · 30 days",
        "detail": f"{ai['calls']:,} provider calls · {actions:,} actions",
    }


def _check_jobs(db: Session) -> dict:
    latest: dict[str, models.JobRun] = {}
    for run in db.scalars(
        select(models.JobRun).order_by(models.JobRun.started_at.desc())
    ).all():
        latest.setdefault(run.job, run)
    if not latest:
        return {
            "key": "jobs",
            "status": "unknown",
            "value": "—",
            "detail": "No background job runs recorded yet",
        }
    failed = [name for name, run in latest.items() if run.status == "failed"]
    running = [name for name, run in latest.items() if run.status == "running"]
    if failed:
        return {
            "key": "jobs",
            "status": "check",
            "value": f"{len(failed)} job(s) failing",
            "detail": "Latest failure: " + ", ".join(sorted(failed)),
        }
    return {
        "key": "jobs",
        "status": "watch" if running else "ok",
        "value": f"{len(latest)} jobs on schedule",
        "detail": (
            "One run is in progress" if running else "Every job's latest run finished clean"
        ),
    }


def _health(db: Session, windows) -> dict:
    checks = [
        _check_database(db),
        _check_storage(),
        _check_backup(db),
        _check_email(db, windows),
        _check_stripe(db, windows),
        _check_ai(db, windows),
        _check_jobs(db),
    ]
    return {
        "checks": checks,
        "ok_count": sum(1 for c in checks if c["status"] == "ok"),
        "total": len(checks),
    }


# -- the payload -----------------------------------------------------------


def panel_payload(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    windows = _windows(now)
    return {
        "generated_at": now.isoformat(),
        "overview": _overview(db, windows, now),
        "scoreboard": _scoreboard(db, windows),
        "health": _health(db, windows),
    }
