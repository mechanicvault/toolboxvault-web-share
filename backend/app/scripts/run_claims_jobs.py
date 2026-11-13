"""Claims job seam: the periodic deadline chores.

The compose `jobs` service (app/scripts/scheduler.py) runs this
on its cadence; it also runs standalone as a one-shot:

    python -m app.scripts.run_claims_jobs

It performs the state-keeping jobs the claims module defines:

  1. Deadline notifications (claims.run_deadline_notifications) —
     every claim whose proof-of-loss deadline or recoverable
     depreciation deadline is due within 7 days (or overdue)
     earns its owner ONE inbox notification per (claim, deadline,
     due date). Idempotent: re-runs create nothing, and a deadline
     MOVED to a new date earns a fresh notification for that date.
  2. Backorder reminders (claims.run_backorder_reminders) —
     every warranty claim sitting in the Backordered status owes
     its owner and its seated counterparty ONE inbox reminder a
     month, from a month after it entered the status. The claim's
     own last-reminded stamp makes re-runs inside a month no-ops.
"""

from app.core.db import SessionLocal
from app.modules.claims import readiness, service


def run(db) -> str:
    created = service.run_deadline_notifications(db)
    backorders = service.run_backorder_reminders(db)
    # Audit A8: claim-readiness nudges ride the same seam (their
    # own interval + silence + kill-switch rules gate them inside).
    nudges = readiness.run_readiness_nudges(db)
    return (
        f"claims jobs: {created} deadline notification(s) created, "
        f"{backorders} backorder reminder(s) sent, "
        f"{nudges} readiness nudge(s) sent"
    )


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
