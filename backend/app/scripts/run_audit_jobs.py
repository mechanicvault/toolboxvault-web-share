"""Audit-trail jobs (user history, 2026-10-19): daily restore
markers + retained-file purge.

Run like the other job scripts (a thin main over SessionLocal):
  python -m app.scripts.run_audit_jobs

Daily markers: one per user per day at most, only for users whose
change journal moved since their last marker. Purge: tombstoned
storage objects older than the admin setting
`audit.retention_days` (default 180) are hard-deleted — rows and
bytes — ending the restore window for those files.
"""

from app.core.db import SessionLocal
from app.modules.core import journal


def run(db) -> str:
    markers = journal.run_daily_markers(db)
    purged = journal.purge_expired_files(db)
    return f"audit jobs: {markers} daily markers, {purged} files purged"


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
