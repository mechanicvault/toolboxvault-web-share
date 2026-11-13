"""Backfill print-photo renditions (prints thumbnails lane,
2026-11-10).

Browse cards and the detail gallery used to serve each print
photo's full original bytes. Renditions (card 320 / display
1600, the inventory pipeline's derived-key cache — see
app/modules/prints/renditions.py) are now generated at upload
and lazily on read, so the shelf heals itself; this one-shot
generates them AHEAD of first reads for everything already
live, so no visitor pays a first-read generation.

    python -m app.scripts.backfill_print_renditions [--dry-run]

Run inside the api service (docker compose exec api ...).
Idempotent: a rendition already in storage is skipped, so a
re-run is a quiet no-op apart from anything genuinely new.
--dry-run reports what WOULD be generated and writes nothing.

Scope: photos on LIVE listings — every PrintMedia photo's
storage key, plus every live file's cover (preview_key) that
has no media row behind it (the pre-showcase covers). Removed
listings are skipped: their doors 404, nothing serves them.
Originals are never modified or deleted.
"""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.prints import models, renditions


def _photo_keys(db: Session) -> list[str]:
    keys: set[str] = set()
    media_keys = db.scalars(
        select(models.PrintMedia.storage_key)
        .join(
            models.PrintFile,
            models.PrintFile.id == models.PrintMedia.file_id,
        )
        .where(
            models.PrintMedia.kind == "photo",
            models.PrintFile.status == "live",
        )
    ).all()
    keys.update(k for k in media_keys if k)
    cover_keys = db.scalars(
        select(models.PrintFile.preview_key).where(
            models.PrintFile.status == "live",
            models.PrintFile.preview_key.is_not(None),
        )
    ).all()
    keys.update(k for k in cover_keys if k)
    return sorted(keys)


def run(db: Session, *, dry_run: bool = False) -> dict:
    """Generate every missing rendition for live listings'
    photos. Returns the tally:
    {keys, generated, already_present, would_generate, failed}
    (would_generate is the dry-run count; failed counts photos
    whose bytes can't be decoded — those keep serving their
    original, as they always have)."""
    keys = _photo_keys(db)
    tally = {
        "keys": len(keys),
        "generated": 0,
        "already_present": 0,
        "would_generate": 0,
        "failed": 0,
    }
    for key in keys:
        for width in renditions.WIDTHS:
            if renditions.variant_exists(key, width):
                tally["already_present"] += 1
                continue
            if dry_run:
                tally["would_generate"] += 1
                continue
            if renditions.rendition(key, width) is not None:
                tally["generated"] += 1
            else:
                tally["failed"] += 1
    return tally


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate missing print-photo renditions."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be generated; write nothing.",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        tally = run(db, dry_run=args.dry_run)
    mode = " (dry run)" if args.dry_run else ""
    print(
        "print renditions{mode}: {keys} photo keys — "
        "{generated} generated, {already_present} already present, "
        "{would_generate} would generate, {failed} undecodable "
        "(those keep serving their original)".format(mode=mode, **tally)
    )


if __name__ == "__main__":
    main()
