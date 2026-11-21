"""Business-day time.

The business runs on America/Chicago time, so every "today"
in the admin numbers — site pulse windows, admin panel
windows, the daily site-stats snapshot and its per-day
counts — is the CHICAGO calendar day, not the UTC day. (After
6 pm Central the UTC day is already tomorrow; the old UTC
windows showed tomorrow's numbers as "today" every evening.)

One frame, everywhere: a business date is the calendar date
of an instant in America/Chicago, and a business day's bounds
are that date's Chicago midnights expressed in UTC (DST-safe —
each midnight is converted on its own, never start + 24h).
Timestamps stay stored in UTC; only the day framing moves.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("America/Chicago")


def business_date(now: datetime) -> date:
    """The business calendar date containing the instant."""
    return now.astimezone(BUSINESS_TZ).date()


def business_day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) UTC instants of one business day."""
    start = datetime.combine(day, time.min, tzinfo=BUSINESS_TZ)
    end = datetime.combine(
        day + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ
    )
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def business_today_bounds(
    now: datetime,
) -> tuple[date, datetime, datetime]:
    """(business date, start, end) for the day containing now."""
    day = business_date(now)
    start, end = business_day_bounds(day)
    return day, start, end
