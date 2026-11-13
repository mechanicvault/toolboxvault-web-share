"""Flyer job seam: the standing flyer URL pulls (owner order,
2026-11-05 #10).

The compose `jobs` service (app/scripts/scheduler.py) runs
this daily; it also runs standalone as a one-shot:

    python -m app.scripts.run_flyer_jobs

Every source with a standing web address gets fetched through
the manuals import's SSRF-guarded download; a changed flyer
posts as the source's current flyer (and notifies), an
unchanged one is hash-deduped. The same run then works the
platform's official flyer links: directory companies whose
brand publishes a flyer online get it posted under their
company spot automatically, unless the spot's poster set
their own standing address (which always wins). Per-source
failures are counted in the summary, never fatal.
"""

from app.core.db import SessionLocal
from app.modules.flyers import service


def run(db) -> str:
    return service.run_standing_pulls(db)


def main() -> None:
    with SessionLocal() as db:
        print(run(db))


if __name__ == "__main__":
    main()
