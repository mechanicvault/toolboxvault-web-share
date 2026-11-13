"""Agent invite reminder job seam: the 30-day unclaimed-record
nudge (owner order, 2026-11-07).

The compose `jobs` service (app/scripts/scheduler.py) runs this
daily; it also runs standalone as a one-shot:

    python -m app.scripts.run_agent_invite_jobs

The sweep (dealers.invite_reminders.run_agent_invite_reminders)
sends a private agent record's owner ONE inbox reminder when
the record has sat unclaimed for 30 days — invite your agent
to join the network. Once-ever per record by construction (the
record's own invite_reminded_at stamp), so a re-run is a quiet
no-op.
"""

from app.core.db import SessionLocal
from app.modules.dealers import invite_reminders


def run(db) -> str:
    sent = invite_reminders.run_agent_invite_reminders(db)
    return f"agent invite reminders: {sent} sent"


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
