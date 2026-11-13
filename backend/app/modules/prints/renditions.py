"""Size-appropriate renditions of print-listing photos.

The disease (owner-caught live, 2026-11-10): browse cards and
the detail gallery served each photo's FULL original bytes —
the one live listing's cover was 3,243,527 bytes at 5712×4284,
downloaded whole into a card a few hundred pixels wide. Uploads
are allowed to 10 MB and were stored and served as-is; with a
shelf of thousands of files that is a serious bandwidth and
decode cost on every browse.

The cure reuses the inventory photo pipeline wholesale
(app.modules.inventory.thumbs): a rendition is a Pillow
thumbnail, JPEG re-encoded (quality 78), stored back into
object storage under the derived key `<key>.thumb<width>.jpg`
and generated lazily on first read — so this module adds no
parallel resizer, no new storage scheme, and one behavior:

  * CARD (320) — the browse cards and the record header plate.
    320 is the inventory tile width, and the prints cards
    render in the same few-hundred-pixel band.
  * DISPLAY (1600) — the detail page's gallery tiles, the
    media viewer, and the cover's big-preview modal: bounded
    at 1600px on the long edge, big enough for a full-screen
    look, a fraction of a multi-MB original.

What prints does NOT reuse: the inventory endpoint's signed
capability URLs. Inventory photos are private, so their
rendition endpoint rides an HMAC URL; print photos are public
by design and are served through the listing-scoped routes
(/files/{id}/preview, /files/{id}/media/{media_id}), which
resolve the storage key from the row — the row IS the
capability. For the same reason inventory's WIDTHS allowlist
(theirs is the set their signed endpoint may mint) is left
untouched; these two widths are prints' own constants, passed
to the shared rendition generator.

Originals are NEVER modified or deleted by rendition work.
A photo that can't be decoded yields no rendition and every
caller falls back to serving the original, exactly as before.
"""

from app.core.storage import StorageError, storage
from app.modules.inventory import thumbs

CARD_WIDTH = 320
DISPLAY_WIDTH = 1600

WIDTHS = (CARD_WIDTH, DISPLAY_WIDTH)


def variant_key(key: str, width: int) -> str:
    """The derived storage key a rendition lives under (the
    inventory scheme: `<key>.thumb<width>.jpg`)."""
    return thumbs.variant_key(key, width)


def rendition(key: str, width: int) -> bytes | None:
    """The rendition bytes for `key` at `width` — the shared
    generator: storage-cached, generated on first read. None
    when the original can't be decoded (callers fall back to
    the original bytes)."""
    try:
        return thumbs.rendition(key, width)
    except Exception:
        # The shared generator already swallows storage and
        # decode failures; this guard keeps an unexpected
        # storage-layer error from ever breaking a public read
        # — the fallback (the original) is always safe.
        return None


def card(key: str) -> bytes | None:
    return rendition(key, CARD_WIDTH)


def display(key: str) -> bytes | None:
    return rendition(key, DISPLAY_WIDTH)


def ensure_variants(key: str) -> dict[int, bool]:
    """Generate BOTH renditions for a freshly stored photo
    (upload time), so first reads are plain storage fetches.
    Returns {width: generated?}. Never raises: the original
    is the source of truth and a rendition failure must not
    fail an upload — a missing rendition is retried lazily
    on read and by the backfill."""
    made: dict[int, bool] = {}
    for width in WIDTHS:
        made[width] = rendition(key, width) is not None
    return made


def variant_exists(key: str, width: int) -> bool:
    try:
        storage.head(variant_key(key, width))
        return True
    except Exception:
        return False


def delete_variants(key: str) -> None:
    """Remove a photo's renditions (its original is being
    deleted by the caller — media removal). Quiet, like the
    service's own _delete_quietly: a leftover derived key is
    unreachable once its row is gone, but storage stays tidy.
    """
    for width in WIDTHS:
        try:
            storage.delete(variant_key(key, width))
        except StorageError:
            pass
        except Exception:
            pass
