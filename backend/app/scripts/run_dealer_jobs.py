"""Dealer job seam: route-day reminders (audit A2).

The compose `jobs` service (app/scripts/scheduler.py) runs this
on its cadence; it also runs standalone as a one-shot:

    python -m app.scripts.run_dealer_jobs

The reminder (dealers.route_days.run_route_day_reminders) is
idempotent per (profile, route date): a dealer hears once on
each route day.
"""

from app.core.db import SessionLocal
from app.modules.dealers import route_days


def run(db) -> str:
    sent = route_days.run_route_day_reminders(db)
    return f"dealer route-day reminders: {sent} sent"


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
