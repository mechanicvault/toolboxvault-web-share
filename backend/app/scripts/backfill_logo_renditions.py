"""Backfill dealer-logo renditions (image-delivery sweep
follow-on, 2026-11-10).

Directory tiles and Home widget strips used to download each
dealer logo's FULL harvested original — the audit's stress
case was a 5.8 MB transparent PNG in a ~100px tile. Logos now
serve a 320px rendition (alpha-preserving PNG for marks with
real transparency, the photo pipeline's JPEG for opaque
ones — see app/modules/inventory/logo_thumbs.py), generated
lazily on first read by dealers' logo_url_for, so the
directory heals itself; this one-shot generates them AHEAD
of first reads for the whole harvested set, so no visitor
pays a first-read generation.

    python -m app.scripts.backfill_logo_renditions [--dry-run]

Run inside the api service (docker compose exec api ...).
Idempotent: a rendition already in storage is skipped, so a
re-run is a quiet no-op apart from anything genuinely new.
--dry-run reports what WOULD be generated and writes nothing.

Scope: the bounded platform prefix `platform/logos/` — the
harvested brand marks (DealerCompany.logo_key). It is swept
from STORAGE, not the dealer tables, so marks whose rows
were edited or removed are covered too. Two deliberate
exclusions:

  * SVG objects: no variant by design — SVG is already the
    optimal bytes for a logo slot and Pillow cannot
    rasterize it. Counted as skipped_svg.
  * Personal-edit logo keys outside the prefix (a viewer's
    own override key): those heal lazily on that viewer's
    first read, by the same logo_thumbs.rendition path.

Originals are never modified or deleted. An undecodable
object is reported (failed) and keeps serving its original,
as it always has.
"""

import argparse
import re

from app.core.storage import storage
from app.modules.dealers.service import LOGO_VARIANT_WIDTH
from app.modules.inventory import logo_thumbs

LOGO_PREFIX = "platform/logos/"

# A derived rendition key (<original>.thumb<width>.jpg|png)
# is not itself a logo — never feed renditions back in as
# sources.
_VARIANT_KEY = re.compile(r"\.thumb\d+\.(?:jpg|png)$")


def _logo_keys() -> list[str]:
    keys = storage.list_keys(LOGO_PREFIX)
    return sorted(k for k in keys if not _VARIANT_KEY.search(k))


def run(*, dry_run: bool = False) -> dict:
    """Generate every missing logo rendition under the
    platform prefix. Returns the tally:
    {keys, generated, already_present, would_generate,
    skipped_svg, failed} (would_generate is the dry-run
    count; failed counts objects whose bytes can't be
    decoded — those keep serving their original)."""
    keys = _logo_keys()
    tally = {
        "keys": len(keys),
        "generated": 0,
        "already_present": 0,
        "would_generate": 0,
        "skipped_svg": 0,
        "failed": 0,
    }
    for key in keys:
        if logo_thumbs.is_svg_key(key):
            tally["skipped_svg"] += 1
            continue
        if logo_thumbs.variant_exists(key, LOGO_VARIANT_WIDTH):
            tally["already_present"] += 1
            continue
        if dry_run:
            tally["would_generate"] += 1
            continue
        if logo_thumbs.generate(key, LOGO_VARIANT_WIDTH) is not None:
            tally["generated"] += 1
        else:
            tally["failed"] += 1
    return tally


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate missing dealer-logo renditions."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be generated; write nothing.",
    )
    args = parser.parse_args()
    tally = run(dry_run=args.dry_run)
    mode = " (dry run)" if args.dry_run else ""
    print(
        "logo renditions{mode}: {keys} logo objects — "
        "{generated} generated, {already_present} already present, "
        "{would_generate} would generate, {skipped_svg} SVG "
        "(no variant by design), {failed} undecodable "
        "(those keep serving their original)".format(mode=mode, **tally)
    )


if __name__ == "__main__":
    main()
