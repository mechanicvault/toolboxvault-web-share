"""Feature announcement job seam (release machinery, owner
rule 2026-11-08): the fan-out behind Admin -> Announcements.

The compose `jobs` service (app/scripts/scheduler.py) runs this
every minute; it also runs standalone as a one-shot:

    python -m app.scripts.run_announcement_jobs

The sweep (core/announcements.run_pending_announcements) sends
every queued announcement to every ACTIVE account as an inbox
notification and flips its history row to "sent" with the
recipient count. Idempotent by status: only queued (or
previously failed) rows are picked up, and a send's rows + flip
commit together, so a re-run is a quiet no-op.
"""

from app.core.db import SessionLocal
from app.modules.core import announcements


def run(db) -> str:
    sent = announcements.run_pending_announcements(db)
    return f"feature announcements: {sent} sent"


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
