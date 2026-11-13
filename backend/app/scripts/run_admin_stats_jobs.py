"""Admin stats snapshot job (admin lane, owner 2026-11-06).

Writes the day's Site Stats snapshot row (users per tier,
free/paying counts, MRR — the state-shaped figures the admin
Site Stats widget diffs day over day). Runs daily on the jobs
service via the scheduler (job name "admin-stats"). Idempotent:
re-running refreshes today's row; past days are never rewritten
— a day with no run simply has no baseline, and the surfaces
say so honestly.
"""

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.core import site_stats


def run(db: Session) -> dict:
    return site_stats.run_daily_snapshot(db)


def main() -> None:
    with SessionLocal() as db:
        result = run(db)
    print(result)


if __name__ == "__main__":
    main()
