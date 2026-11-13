"""Marketplace job seam: the periodic reputation chores.

The compose `jobs` service (app/scripts/scheduler.py) runs this
on its cadence; it also runs standalone as a one-shot:

    python -m app.scripts.run_marketplace_jobs

It performs the one state-keeping job reputation defines:

  1. The 14-day publication sweep (reputation.publish_due) —
     every rating still in its double-blind hold whose pair is
     complete publishes both; a LONE rating publishes anyway once
     its interaction is 14 days old (owner's hybrid rule: silence
     is not a veto). The same rule is also applied lazily on every
     reputation read, so this sweep is the guarantee, not the only
     path. Idempotent: re-runs publish nothing twice.
"""

from app.core.db import SessionLocal
from app.modules.marketplace import reputation


def run(db) -> str:
    published = reputation.publish_due(db)
    return f"marketplace jobs: {published} rating(s) published"


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
