"""Backup report content: the weekly digest + failure alerts.

Pure builders (runs in -> email text out) so the wording is
unit-testable without a database or a mail transport. The owner
reads these — plain English, no jargon, and a failure alert always
answers three questions: what happened, why (the likely cause),
and how to fix it.

Delivery goes through the app's email seam
(app.core.notifications.send_email) from job.py; this module only
writes the words.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RunView:
    """The slice of a backup_runs row the reports need. job.py
    builds these from ORM rows; tests build them directly."""

    started_at: datetime
    bundle_name: str | None
    size_bytes: int | None
    status: str
    detail: dict


# How each stage's failure is explained to the owner: what it
# means, the likely cause, and the fix. Keyed by the stage names
# job.py records in detail["stage"].
STAGE_GUIDANCE: dict[str, tuple[str, str, str]] = {
    "database_dump": (
        "The database could not be copied.",
        "The database container was down or unreachable, its disk "
        "was full, or its password changed without the backup "
        "service being told.",
        "Check the server: 'docker compose ps' should show the "
        "postgres container healthy. If the disk is full, free "
        "space and the next nightly run will recover on its own.",
    ),
    "storage_export": (
        "Your stored files (photos and documents) could not be copied.",
        "The storage service was down or unreachable, or its "
        "credentials changed without the backup service being told.",
        "Check the server: 'docker compose ps' should show the "
        "storage container up. The next nightly run retries "
        "automatically.",
    ),
    "source_copy": (
        "The website's own code could not be copied into the bundle.",
        "The backup service could not read the deployed source "
        "tree — usually a permissions change on the server.",
        "Check that the app directory on the server is readable "
        "by Docker, then the next nightly run will recover.",
    ),
    "archive": (
        "The backup bundle could not be packed into its single file.",
        "Almost always a full disk in the backup staging area.",
        "Free disk space on the server (old bundles beyond the "
        "newest 7 are safe to delete), then the next run recovers.",
    ),
    "encrypt": (
        "The bundle could not be encrypted.",
        "The encryption key in the server settings is damaged or "
        "in the wrong format.",
        "The encryption public key needs to be re-entered in the "
        "server .env (BACKUP_AGE_PUBLIC_KEY). Until then bundles "
        "are kept on the server UNENCRYPTED and are never uploaded.",
    ),
    "upload": (
        "The finished bundle could not be sent to Google Drive.",
        "The backup Drive connection was revoked or expired, or "
        "the Drive account is out of space.",
        "Reconnect in Admin → Settings → Backups (\"Connect backup "
        "Drive\"), or free space in the Drive account. The bundle "
        "is safe on the server meanwhile and uploads resume with "
        "the next run.",
    ),
    "verify": (
        "The copy in Google Drive did not match the bundle that was sent.",
        "The upload was cut off or corrupted on the way — the "
        "mismatch check caught it, which is the check doing its job.",
        "No action needed: the bad copy is not trusted, the good "
        "bundle is still on the server, and the next nightly run "
        "sends a fresh one. If this repeats, the server's internet "
        "connection is unstable.",
    ),
    "record": (
        "The backup's bookkeeping could not be written.",
        "The database was briefly unavailable while the job was "
        "finishing up.",
        "If the next digest looks normal, ignore this. If it "
        "repeats, the database container needs attention.",
    ),
}


def _mb(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "size unknown"
    return f"{size_bytes / 1_000_000:.1f} MB"


def status_plain(status: str) -> str:
    """One plain-English phrase per run status."""
    return {
        "ok": "complete — encrypted, uploaded to Drive, and verified",
        "local_only": "complete on the server (off-site upload not set up yet)",
        "encryption_not_configured": (
            "complete on the server, NOT encrypted "
            "(encryption key not set up yet)"
        ),
        "failed": "FAILED",
        "running": "still running (or stopped mid-run)",
    }.get(status, status)


def build_failure_alert(
    run: RunView,
    *,
    streak_started_at: datetime | None = None,
    failure_count: int = 1,
) -> tuple[str, str]:
    """(subject, body) for a failed run.

    The streak arguments carry the alert policy's context
    (app/core/backup_alerts.py): when this failure is a
    continuing streak's daily re-alert rather than its first,
    the email says so — how long the trouble has been running
    and how many attempts it has eaten — instead of pretending
    to be a brand-new event."""
    detail = run.detail or {}
    stage = str(detail.get("stage") or "record")
    error = str(detail.get("error") or "unknown error")
    what, cause, fix = STAGE_GUIDANCE.get(
        stage,
        (
            "A backup step failed.",
            "An unexpected error — the technical detail is below.",
            "If this repeats, the backup service needs attention.",
        ),
    )
    when = run.started_at.strftime("%A %B %d, %Y at %H:%M UTC")
    reminder = failure_count > 1 and streak_started_at is not None
    if reminder:
        subject = f"Toolbox Vault backup STILL FAILING — {when}"
        streak_paragraph = (
            f"This is failed run #{failure_count} in a row — the "
            "streak began "
            + streak_started_at.strftime("%A %B %d, %Y at %H:%M UTC")
            + ". You were alerted when it started; while it keeps "
            "failing you get at most one of these a day, and one "
            "notice when a backup completes again. The nightly "
            "job keeps retrying on its own.\n\n"
        )
    else:
        subject = f"Toolbox Vault backup FAILED — {when}"
        streak_paragraph = (
            "The nightly job keeps retrying on its own — if it "
            "keeps failing you get at most one alert a day, and "
            "one notice when a backup completes again.\n\n"
        )
    body = (
        "A nightly Toolbox Vault backup did not complete.\n\n"
        f"When: {when}\n"
        f"What happened: {what}\n"
        f"Stage: {stage}\n"
        f"Likely cause: {cause}\n"
        f"How to fix it: {fix}\n\n"
        + streak_paragraph
        + "Your website itself is unaffected — this is only about "
        "the backup copy. The previous good backups are untouched.\n\n"
        f"Technical detail: {error}\n"
    )
    return subject, body


def build_recovery_alert(
    run: RunView,
    *,
    streak_started_at: datetime,
    failure_count: int,
) -> tuple[str, str]:
    """(subject, body) for the first completed run after an
    alerted failure streak — the all-clear that closes the
    loop. The run's own status line rides along verbatim
    (status_plain), so a recovery that only completes locally
    says exactly that instead of claiming the off-site copy
    is whole."""
    when = run.started_at.strftime("%A %B %d, %Y at %H:%M UTC")
    since = streak_started_at.strftime("%A %B %d, %Y at %H:%M UTC")
    subject = f"Toolbox Vault backup recovered — {when}"
    body = (
        "Good news: the nightly Toolbox Vault backup is "
        "completing again.\n\n"
        f"Latest run: {when} — {status_plain(run.status)}.\n"
        f"The failure streak began {since} and ran to "
        f"{failure_count} failed run(s) before this one. The "
        "newest bundle is in place; your website was unaffected "
        "at every point, and the good backups from before the "
        "streak were never touched.\n"
    )
    return subject, body


def build_digest(
    runs: list[RunView],
    *,
    total_vault_bytes: int,
    drill_status: str,
    any_failed: bool,
) -> tuple[str, str]:
    """(subject, body) for the weekly digest.

    `runs` is the week's runs, oldest first. `total_vault_bytes`
    is the combined size of everything the vault currently holds
    (local staging + Drive, as measured by job.py). `drill_status`
    is a one-line statement of the last restore drill.
    """
    if runs:
        first = runs[0].started_at.strftime("%B %d")
        last = runs[-1].started_at.strftime("%B %d, %Y")
        span = f"{first} – {last}"
    else:
        span = "this week"
    if any_failed:
        subject = f"Toolbox Vault backups — week of {span}: ATTENTION NEEDED"
        headline = (
            "One or more backups FAILED this week — see the lines "
            "marked FAILED below. (A separate alert email was sent "
            "for each failure with the cause and the fix.)"
        )
    else:
        subject = f"Toolbox Vault backups — week of {span}: all completed"
        headline = "Every nightly backup completed this week."
    lines = [
        headline,
        "",
        "This week's backups:",
    ]
    if not runs:
        lines.append("  (no backup runs recorded this week — that is itself a problem)")
    for run in runs:
        day = run.started_at.strftime("%a %b %d")
        name = run.bundle_name or "(no bundle)"
        lines.append(
            f"  {day}: {name} — {_mb(run.size_bytes)} — {status_plain(run.status)}"
        )
    lines += [
        "",
        f"Total vault size right now: {_mb(total_vault_bytes)} "
        "(the newest 7 daily bundles are kept; older ones are "
        "deleted automatically).",
        f"Restore drill status: {drill_status}",
        "",
        "If a backup ever fails, you get a separate email right "
        "away saying what happened, why, and how to fix it — this "
        "digest is just the weekly all-clear (or summary).",
    ]
    return subject, "\n".join(lines) + "\n"
