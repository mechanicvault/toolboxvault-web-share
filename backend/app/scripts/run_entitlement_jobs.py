"""Entitlement job seam (Phase A1): the periodic billing chores.

The compose `jobs` service (app/scripts/scheduler.py) runs this
on its cadence; it also runs standalone as a one-shot:

    python -m app.scripts.run_entitlement_jobs

It performs the two state-keeping jobs the entitlement engine
defines:

  1. Lapse transitions (billing.entitlements.run_lapse_transitions)
     — subscriptions whose paid period AND 20-day grace window have
     passed flip to "ended". Resolution already computes the drop
     to Free without this; the flip keeps stored facts honest.
  2. AI allowance refills (billing.wallet.refill_all_allowances) —
     idempotent per month: each wallet's allowance bucket is set to
     its plan's monthly amount (no rollover). Safe to run daily;
     only the first run of a month lands.
"""

from app.core.db import SessionLocal
from app.modules.billing import entitlements, wallet


def run(db) -> str:
    """The work, on a caller-owned session (the scheduler calls
    this; main() below is the one-shot CLI). Returns the summary
    line the run is recorded under."""
    transitioned = entitlements.run_lapse_transitions(db)
    refilled = wallet.refill_all_allowances(db)
    return (
        f"entitlement jobs: {transitioned} subscription(s) lapsed, "
        f"{refilled} wallet(s) refilled"
    )


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
