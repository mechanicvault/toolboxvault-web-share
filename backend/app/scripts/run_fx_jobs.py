"""FX job seam: the daily exchange-rate refresh.

The compose `jobs` service (app/scripts/scheduler.py) runs this
daily; it also runs standalone as a one-shot:

    python -m app.scripts.run_fx_jobs

Fetches the ECB reference rates via frankfurter.app (free, no
key) into the fx_rates cache. A failed fetch raises here, the
scheduler ledgers the run as failed, and YESTERDAY'S RATES STAY —
the display hints keep working off the stale cache (they are
marked approximate anyway), and the next day retries.
"""

from app.core.db import SessionLocal
from app.modules.core import money


def run(db) -> str:
    return money.run_fx_refresh(db)


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
