"""Maintenance job seam: the periodic care chores.

The compose `jobs` service (app/scripts/scheduler.py) runs this
on its cadence; it also runs standalone as a one-shot:

    python -m app.scripts.run_maintenance_jobs

It performs the one state-keeping job the maintenance module
defines:

  1. Overdue-schedule notifications
     (maintenance.run_overdue_notifications) — every schedule whose
     computed next due has slipped into the past earns its owner
     ONE inbox notification per (schedule, due date). Idempotent:
     re-runs create nothing, and a schedule that is logged done
     and comes due again on a NEW date earns a fresh notification
     for that date.
"""

from app.core.db import SessionLocal
from app.modules.maintenance import service


def run(db) -> str:
    created = service.run_overdue_notifications(db)
    return f"maintenance jobs: {created} overdue notification(s) created"


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
