"""The backup-failure alert policy — shared by the user cloud
backups (modules/core/cloud_backup.py) and the platform Disaster
Vault (app/backup/job.py).

Why this exists (2026-10-30): a user's Drive connection died
(Google's token endpoint answering HTTP 400) and the backup kept
failing every hour. The old behavior alerted on EVERY failure —
fifteen identical "Cloud backup failed" emails in fifteen
hours. A stream like that trains both the owner and their mail
provider to ignore it (the owner's alerts stopped reaching him
at all partway through the day, while the failures continued),
and a success afterwards said nothing. Alerting that cries
hourly and then goes quiet at the moment it matters is worse
than a policy, so the policy is now explicit:

  1. The FIRST failure of a streak alerts immediately.
  2. While the same streak keeps failing, re-alert at most once
     per 24 hours — a continuing failure is never fully silent.
  3. When a run succeeds again after an alerted streak, ONE
     recovery notice closes the loop.

"Streak" = consecutive failed runs with no completed run in
between. This module is pure (ledger slices in -> decisions
out) so the policy is unit-testable without a database: each
caller reads its own run ledger + its own record of past
alerts and asks. The callers own what an "alert" is — for user
backups the inbox notification (whose email twin follows the
owner's channel preferences, as every notification does); for
the Disaster Vault the report email to the operator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# A continuing failure re-alerts at most this often.
REALERT_AFTER = timedelta(hours=24)


@dataclass(frozen=True)
class Streak:
    """A run of consecutive failures at the head of a ledger."""

    started_at: datetime | None  # when the streak's FIRST failure began
    count: int  # how many failed runs the streak holds


EMPTY_STREAK = Streak(started_at=None, count=0)


def as_utc(moment: datetime) -> datetime:
    """Ledger timestamps can read back naive (SQLite); every
    ledger here is UTC, so a naive value IS UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def leading_streak(outcomes: list[tuple[datetime, bool]]) -> Streak:
    """The failure streak at the HEAD of a newest-first outcome
    list: (run started_at, is_failure) pairs, newest first. The
    streak is the unbroken run of failures before the first
    non-failure; EMPTY when the newest outcome is a success (or
    the list is empty)."""
    count = 0
    started_at: datetime | None = None
    for started, failed in outcomes:
        if not failed:
            break
        count += 1
        started_at = started
    if count == 0:
        return EMPTY_STREAK
    return Streak(started_at=started_at, count=count)


def failure_alert_due(now: datetime, alert_times: list[datetime]) -> bool:
    """Should this failure alert NOW? `alert_times` = when the
    alerts for THIS streak already went out. The first failure
    of a streak always alerts; after that, at most once per
    REALERT_AFTER while the streak continues."""
    if not alert_times:
        return True
    return as_utc(now) - max(as_utc(t) for t in alert_times) >= REALERT_AFTER


def recovery_notice_due(streak: Streak, alerts_in_streak: int) -> bool:
    """A success closes the loop only when there WAS a failure
    streak and somebody was actually told about it — a silent
    blip nobody heard about needs no all-clear."""
    return streak.count > 0 and alerts_in_streak > 0
