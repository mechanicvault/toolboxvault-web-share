"""The background-jobs scheduler (step-4 fix round, 2026-10-20).

Until this build the five run_*_jobs scripts had NO scheduler:
entitlement lapse transitions + AI refills, maintenance overdue
notifications, claims deadline notifications, the marketplace
14-day rating publication sweep and the audit daily markers +
tombstone purge existed as code but never ran in production.

This is the lightest production-grade mechanism the stack allows:
a dedicated `jobs` service in docker-compose running this loop —
the same shape as the Disaster Vault backup scheduler
(app/backup/scheduler.py): wake every minute, run whatever is
due, record every run. No new infrastructure, no paid cron.

Cadences (minutes) — each job is idempotent, so running early or
twice is harmless; the intervals are chosen by how stale their
output may get, not by cost:

  entitlements  60   lapse transitions gate the active set read
                     paths already compute live, so an hour of
                     stored-state lag is invisible; AI refills
                     only land on the first run of a month.
  maintenance   60   overdue notifications — hourly is prompt
                     without being noisy (deduped per due date).
  claims       240   deadline notifications — deadlines are
                     day-granular; 4h keeps them same-day fresh.
  marketplace 1440   the 14-day rating publication sweep; the
                     read path ALSO publishes lazily, so daily
                     is pure guarantee.
  audit        1440   daily restore markers are day-granular by
                     definition; the tombstone purge rides along.

Every run is ledgered in job_runs (core models.JobRun), the
BackupRun pattern: a row opens "running" when the run starts and
completes ok|failed with the job's summary line (or the error) —
Admin → Settings shows the latest run per job, so a failing job
is visible instead of silent. A job that raises never takes the
loop (or the other jobs) down; it is recorded and retried at its
next cadence.
"""

import importlib
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.core import models


@dataclass(frozen=True)
class JobSpec:
    name: str
    module: str  # module exposing run(db) -> str
    interval_minutes: int


JOBS: tuple[JobSpec, ...] = (
    JobSpec("entitlements", "app.scripts.run_entitlement_jobs", 60),
    JobSpec("maintenance", "app.scripts.run_maintenance_jobs", 60),
    JobSpec("claims", "app.scripts.run_claims_jobs", 240),
    JobSpec("marketplace", "app.scripts.run_marketplace_jobs", 1440),
    JobSpec("audit", "app.scripts.run_audit_jobs", 1440),
    # Wave 2: truck-account due reminders (idempotent per due
    # date; hourly keeps them same-day fresh like maintenance).
    JobSpec("truck", "app.scripts.run_truck_jobs", 60),
    # Audit A2: dealer route-day reminders (idempotent per route
    # date; hourly keeps them same-day fresh like truck).
    JobSpec("dealers", "app.scripts.run_dealer_jobs", 60),
    # Wave 3: the crew 30-day rule's day-25 / expiry notices
    # (idempotent per departure; hourly is plenty for a
    # day-granular clock).
    JobSpec("crew", "app.scripts.run_crew_jobs", 60),
    # Wave 3: the daily FX rate refresh (ECB via frankfurter.app;
    # a failure keeps yesterday's rates and ledgers as failed).
    JobSpec("fx", "app.scripts.run_fx_jobs", 1440),
    # Wave 4: users' Google Drive backups, due per each user's
    # own schedule (daily | weekly) — the job checks hourly and
    # the service decides who is actually due.
    JobSpec("cloud-backups", "app.scripts.run_cloud_backup_jobs", 60),
    # Flyers (2026-11-06): the standing flyer URL pulls — a
    # daily cadence matches the weekly-flyer rhythm; the pull
    # itself is hash-deduped, so an unchanged spot costs one
    # fetch and no notification.
    JobSpec("flyers", "app.scripts.run_flyer_jobs", 1440),
    # Admin stats snapshot (admin lane, 2026-11-06): one Site
    # Stats snapshot row per day for the day-over-day deltas.
    JobSpec("admin-stats", "app.scripts.run_admin_stats_jobs", 1440),
    # Agent invite reminders (owner order, 2026-11-07): a
    # private agent record still unclaimed at 30 days earns its
    # owner one inbox nudge to invite the agent to join — daily
    # cadence is exact for a day-granular 30-day clock, and the
    # reminder is once-ever per record by its own stamp.
    JobSpec("agent-invite-reminders", "app.scripts.run_agent_invite_jobs", 1440),
    # Feature announcements (release machinery, 2026-11-08): an
    # operator-composed announcement sits "queued" until this
    # fans it out to every active account — a 1-minute cadence
    # keeps the send prompt after the click without a request
    # ever looping over the user base. Quiet no-op when the
    # queue is empty.
    JobSpec("announcements", "app.scripts.run_announcement_jobs", 1),
)

WAKE_SECONDS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _last_finished(db: Session, job: str) -> datetime | None:
    """When the job last STARTED a completed (ok or failed) run —
    the cadence clock. A row still "running" belongs to a live or
    crashed attempt and doesn't reset the clock."""
    return db.scalar(
        select(models.JobRun.started_at)
        .where(
            models.JobRun.job == job,
            models.JobRun.status.in_(("ok", "failed")),
        )
        .order_by(models.JobRun.started_at.desc())
        .limit(1)
    )


def is_due(db: Session, spec: JobSpec, now: datetime | None = None) -> bool:
    last = _last_finished(db, spec.name)
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now or _now()) >= last + _interval(spec)


def _interval(spec: JobSpec):
    from datetime import timedelta

    return timedelta(minutes=spec.interval_minutes)


def run_job(db: Session, spec: JobSpec) -> models.JobRun:
    """Run one job NOW, ledgered. Never raises: the outcome —
    success summary or exception — is what's recorded."""
    row = models.JobRun(job=spec.name, status="running", detail={})
    db.add(row)
    db.commit()
    try:
        module = importlib.import_module(spec.module)
        summary = module.run(db)
        row.status = "ok"
        row.detail = {"summary": str(summary)}
    except Exception as exc:  # noqa: BLE001 — a job must not kill the loop
        db.rollback()
        row.status = "failed"
        row.detail = {
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=5),
        }
    row.finished_at = _now()
    db.commit()
    db.refresh(row)
    return row


def run_due(db: Session, now: datetime | None = None) -> list[str]:
    """Run every due job once; returns the names that ran."""
    ran = []
    for spec in JOBS:
        if is_due(db, spec, now):
            run_job(db, spec)
            ran.append(spec.name)
    return ran


def main() -> None:
    print(
        "jobs scheduler: "
        + ", ".join(f"{s.name} every {s.interval_minutes}m" for s in JOBS),
        flush=True,
    )
    while True:
        try:
            with SessionLocal() as db:
                ran = run_due(db)
            if ran:
                print(f"jobs scheduler: ran {', '.join(ran)}", flush=True)
        except Exception as exc:  # noqa: BLE001 — the loop itself must survive
            print(f"jobs scheduler: wake failed: {exc!r}", flush=True)
        time.sleep(WAKE_SECONDS)


if __name__ == "__main__":
    main()
