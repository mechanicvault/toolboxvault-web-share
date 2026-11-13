"""Shop crew job seam: the 30-day rule's day-25 / expiry notices.

The compose `jobs` service (app/scripts/scheduler.py) runs this
on its cadence; it also runs standalone as a one-shot:

    python -m app.scripts.run_crew_jobs

The notices (core.crew.run_grace_notifications) are idempotent
per departure — the membership row's grace_notices ledger is the
memory, so running early or twice sends nothing twice.
"""

from app.core.db import SessionLocal
from app.modules.core import crew


def run(db) -> str:
    sent = crew.run_grace_notifications(db)
    return (
        f"crew grace: {sent['day25']} day-25 notices, "
        f"{sent['expired']} expiry notices"
    )


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
