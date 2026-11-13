"""Cloud backup job (wave 4): run every due Google Drive
backup. A connection is due when its schedule (daily | weekly)
has elapsed since its last successful backup (or it has never
backed up). Each attempt is ledgered by the service and a
failure notifies its owner — one user's dead connection never
blocks the others.

Run: python -m app.scripts.run_cloud_backup_jobs
"""

from app.core.db import SessionLocal
from app.modules.core import cloud_backup, service


def run(db) -> dict:
    due = cloud_backup.due_connections(db)
    ran = ok = 0
    for connection in due:
        user = service.get_user_by_id(db, connection.user_id)
        if user is None:
            continue
        result = cloud_backup.run_backup(db, user, trigger="scheduled")
        ran += 1
        ok += 1 if result.status == "ok" else 0
    return {"checked": len(due), "ran": ran, "ok": ok, "failed": ran - ok}


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
