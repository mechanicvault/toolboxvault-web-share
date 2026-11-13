"""The backup service's scheduler loop (the container's CMD).

Wakes every minute and fires:
  - the nightly bundle at BACKUP_TIME_UTC (default 03:30 UTC),
  - the weekly digest on BACKUP_DIGEST_WEEKDAY at
    BACKUP_DIGEST_TIME_UTC (default Monday 14:00 UTC).

Last-fired dates live in a state file in the backup volume, so a
container restart never double-fires a night or a digest — and a
night the server slept through entirely fires late-but-once on
the next wake rather than leaving a silent gap (the digest lines
the runs up by their real dates either way).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.backup import job
from app.core.config import settings

logger = logging.getLogger("app.backup.scheduler")

STATE_NAME = ".scheduler-state.json"


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.strip().split(":", 1)
    return int(hour), int(minute)


def _load_state(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text())
        except Exception:
            logger.warning("scheduler state unreadable; starting fresh")
    return {}


def _save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state))


def due(now: datetime, state: dict) -> tuple[bool, bool]:
    """(bundle_due, digest_due) for this minute — pure, so the
    firing rules are unit-testable."""
    bundle_h, bundle_m = _parse_hhmm(settings.backup_time_utc)
    today = now.date().isoformat()
    bundle_due = (
        (now.hour, now.minute) >= (bundle_h, bundle_m)
        and state.get("last_bundle_date") != today
    )
    digest_h, digest_m = _parse_hhmm(settings.backup_digest_time_utc)
    digest_due = (
        now.weekday() == settings.backup_digest_weekday
        and (now.hour, now.minute) >= (digest_h, digest_m)
        and state.get("last_digest_date") != today
    )
    return bundle_due, digest_due


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    state_path = backup_dir / STATE_NAME
    logger.info(
        "backup scheduler up: nightly %s UTC, digest weekday %s %s UTC, "
        "keep %s, dir %s",
        settings.backup_time_utc,
        settings.backup_digest_weekday,
        settings.backup_digest_time_utc,
        settings.backup_keep,
        backup_dir,
    )
    while True:
        try:
            now = datetime.now(timezone.utc)
            state = _load_state(state_path)
            bundle_due, digest_due = due(now, state)
            if bundle_due:
                job.run_bundle()
                state["last_bundle_date"] = now.date().isoformat()
                _save_state(state_path, state)
            if digest_due:
                job.run_digest()
                state["last_digest_date"] = now.date().isoformat()
                _save_state(state_path, state)
        except Exception:
            logger.exception("scheduler tick failed; retrying next minute")
        time.sleep(60)


if __name__ == "__main__":
    main()
