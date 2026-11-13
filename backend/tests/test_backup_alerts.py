"""The backup-failure alert policy (app/core/backup_alerts.py).

The 2026-10-30 incident in miniature: a backup failing every
hour must alert ONCE when the streak starts, re-alert at most
once a day while it keeps failing (never fully silent), and
close the loop with exactly one recovery notice when a run
succeeds again. Pure decisions over ledger slices — no
database, no mail.
"""

from datetime import datetime, timedelta, timezone

from app.core import backup_alerts

T0 = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def _outcomes(*spec: tuple[int, bool]) -> list[tuple[datetime, bool]]:
    """(hours_after_T0, is_failure) pairs -> the newest-first
    outcome list the callers build from their ledgers."""
    return [(T0 + h * H, failed) for h, failed in spec]


# -- leading_streak -------------------------------------------------------------


def test_streak_empty_ledger():
    assert backup_alerts.leading_streak([]) == backup_alerts.EMPTY_STREAK


def test_streak_newest_is_success_is_empty():
    streak = backup_alerts.leading_streak(_outcomes((5, False), (4, True)))
    assert streak.count == 0
    assert streak.started_at is None


def test_streak_counts_unbroken_head_and_dates_from_oldest():
    # Newest first: three failures, then a success, then an older failure.
    streak = backup_alerts.leading_streak(
        _outcomes((9, True), (8, True), (7, True), (6, False), (5, True))
    )
    assert streak.count == 3
    assert streak.started_at == T0 + 7 * H  # the streak's FIRST failure


def test_streak_all_failures():
    streak = backup_alerts.leading_streak(_outcomes((2, True), (1, True)))
    assert streak.count == 2
    assert streak.started_at == T0 + 1 * H


# -- failure_alert_due -----------------------------------------------------------


def test_first_failure_always_alerts():
    assert backup_alerts.failure_alert_due(T0, []) is True


def test_within_window_suppressed():
    assert backup_alerts.failure_alert_due(T0 + 23 * H, [T0]) is False
    assert backup_alerts.failure_alert_due(T0 + H, [T0]) is False


def test_at_and_after_window_realerts():
    assert backup_alerts.failure_alert_due(T0 + 24 * H, [T0]) is True
    assert backup_alerts.failure_alert_due(T0 + 49 * H, [T0]) is True


def test_window_runs_from_the_LATEST_alert():
    # Alerts at T0 and T0+20h: the clock restarts at the newest.
    assert backup_alerts.failure_alert_due(T0 + 43 * H, [T0, T0 + 20 * H]) is False
    assert backup_alerts.failure_alert_due(T0 + 44 * H, [T0, T0 + 20 * H]) is True


def test_naive_timestamps_read_as_utc():
    naive = datetime(2026, 10, 30, 6, 0)  # SQLite read-back shape
    assert backup_alerts.failure_alert_due(T0 + H, [naive]) is False
    assert backup_alerts.failure_alert_due(T0 + 25 * H, [naive]) is True


# -- recovery_notice_due ----------------------------------------------------------


def test_recovery_needs_a_streak():
    assert backup_alerts.recovery_notice_due(backup_alerts.EMPTY_STREAK, 3) is False


def test_recovery_needs_an_alerted_streak():
    streak = backup_alerts.Streak(started_at=T0, count=2)
    assert backup_alerts.recovery_notice_due(streak, 0) is False
    assert backup_alerts.recovery_notice_due(streak, 1) is True
