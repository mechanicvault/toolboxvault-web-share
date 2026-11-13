"""Dealer route-day schedules (completeness audit A2, 2026-10-22).

An agent's route is three facts on the profile: a frequency
(weekly / biweekly / monthly), a weekday (0 = Monday .. 6 =
Sunday, date.weekday()), and an anchor date — a day the route
definitely ran, which the biweekly and monthly cycles count from.

next_route_visit computes the next route day on or after a given
date, purely from those facts:

- weekly:   the next date with the route weekday.
- biweekly: anchor + 14k days, the smallest one >= today.
- monthly:  the same weekday at the same week-of-month as the
  anchor (the anchor's week index, capped at the month's last
  such weekday), this month if still ahead, else next month.

The scheduler job (app/scripts/run_dealer_jobs.py) inbox-notifies
the dealer ON each route day, deduped per (profile, date) via the
same system-setting stamp the truck reminders use.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.dealers import models

ROUTE_FREQUENCIES = ("weekly", "biweekly", "monthly")
_REMINDER_SETTING = "dealers.route_reminded"


def _monthly_candidate(year: int, month: int, weekday: int, week_index: int) -> date:
    """The week_index-th (0-based) `weekday` of a month, capped at
    the last one when the month has fewer."""
    days = [
        d
        for d in range(1, calendar.monthrange(year, month)[1] + 1)
        if date(year, month, d).weekday() == weekday
    ]
    return date(year, month, days[min(week_index, len(days) - 1)])


def next_route_visit(
    frequency: str | None,
    day_of_week: int | None,
    anchor: date | None,
    today: date | None = None,
) -> date | None:
    """The next route day on/after `today`, or None when the
    schedule is incomplete (any fact missing)."""
    if frequency not in ROUTE_FREQUENCIES or day_of_week is None or anchor is None:
        return None
    if not 0 <= day_of_week <= 6:
        return None
    today = today or date.today()
    if frequency == "weekly":
        return today + timedelta(days=(day_of_week - today.weekday()) % 7)
    if frequency == "biweekly":
        delta = (today - anchor).days
        if delta <= 0:
            return anchor
        cycles = -(-delta // 14)  # ceil
        return anchor + timedelta(days=14 * cycles)
    # monthly
    week_index = (anchor.day - 1) // 7
    candidate = _monthly_candidate(today.year, today.month, day_of_week, week_index)
    if candidate >= today:
        return candidate
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return _monthly_candidate(year, month, day_of_week, week_index)


def route_next_visit_for(profile: models.AgentProfile, today: date | None = None) -> date | None:
    return next_route_visit(
        profile.route_frequency,
        profile.route_day_of_week,
        profile.route_anchor_date,
        today,
    )


def run_route_day_reminders(db: Session, *, today: date | None = None) -> int:
    """The scheduler job's work: every profile whose route day is
    TODAY hears about it once. Idempotent per (profile, date) —
    the stamp lives in a system setting, the truck-reminder
    pattern; the route day itself re-arms the next cycle because
    the stamp keys on the date."""
    from app.modules.billing import entitlements
    from app.modules.core import inbox

    today = today or date.today()
    reminded = set(entitlements.get_setting(db, _REMINDER_SETTING, []) or [])
    sent = 0
    profiles = list(
        db.scalars(
            select(models.AgentProfile).where(
                models.AgentProfile.route_frequency.is_not(None),
                models.AgentProfile.route_day_of_week.is_not(None),
                models.AgentProfile.route_anchor_date.is_not(None),
            )
        )
    )
    for profile in profiles:
        if route_next_visit_for(profile, today) != today:
            continue
        stamp = f"{profile.id}:{today.isoformat()}"
        if stamp in reminded:
            continue
        inbox.create_notification(
            db,
            profile.user_id,
            kind=inbox.KIND_DEALER_ROUTE_DAY,
            title="Route day",
            body=(
                "Today is your route day. Your next visit after today is "
                + (
                    route_next_visit_for(profile, today + timedelta(days=1))
                    or today
                ).strftime("%A, %B %-d")
                + "."
            ),
            data={"route_date": today.isoformat()},
            commit=False,
        )
        reminded.add(stamp)
        sent += 1
    if sent:
        entitlements.set_setting(db, _REMINDER_SETTING, sorted(reminded))
        db.commit()
    return sent
