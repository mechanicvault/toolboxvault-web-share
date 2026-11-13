"""Truck Accounts job seam: due-soon / overdue reminders.

The compose `jobs` service (app/scripts/scheduler.py) runs this
on its cadence; it also runs standalone as a one-shot:

    python -m app.scripts.run_truck_jobs

The reminders (truck_accounts.run_due_reminders) are idempotent
per (account, due date): a customer hears once that a payment is
coming due and once that it went overdue, the dealer hears once
that it went overdue — and a payment advances the due date,
arming the next cycle.
"""

from app.core.db import SessionLocal
from app.modules.truck_accounts import service as truck_service


def run(db) -> str:
    sent = truck_service.run_due_reminders(db)
    return (
        f"truck reminders: {sent['due_soon']} due-soon, "
        f"{sent['overdue_customer']} overdue (customer), "
        f"{sent['overdue_dealer']} overdue (dealer)"
    )


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
