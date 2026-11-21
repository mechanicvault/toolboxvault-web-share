"""Warranty job seam: the periodic warranty chores.

The compose `jobs` service (app/scripts/scheduler.py) runs this
on its cadence; it also runs standalone as a one-shot:

    python -m app.scripts.run_warranty_jobs

It performs the one state-keeping job the inventory module
defines for warranties:

  1. Warranty expiry warnings
     (inventory.run_warranty_notifications) — every tool/battery
     whose computed warranty end date is 60 / 30 / 3 days out
     earns its owner ONE inbox notification per stage, plus one
     when the warranty has expired. Idempotent per: re-runs create nothing, and an edited term
     (a new end date) earns its own warnings.
"""

from app.core.db import SessionLocal
from app.modules.inventory import service


def run(db) -> str:
    created = service.run_warranty_notifications(db)
    return f"warranty jobs: {created} expiry notification(s) created"


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
