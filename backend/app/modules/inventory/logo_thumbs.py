"""Alpha-preserving logo renditions (image-delivery sweep
follow-on, 2026-11-10).

Dealer logos render in ~100px directory tiles and Home widget
strips, but dealers' logo_url_for presigned the FULL harvested
original — the audit's stress case was a 5,820,798-byte
transparent PNG served whole into a 100px slot. Logos could
not ride the photo pipeline in thumbs.py for two format
reasons:

  * Transparency. thumbs.rendition flattens to JPEG
    (convert("RGB")) — a transparent logo comes back on a
    BLACK background. A logo with real transparency needs an
    alpha-preserving rendition, which is what this module
    adds: the same derived-key scheme with the alpha
    flavor's extension (`<key>.thumb<width>.png`). PNG, not
    WebP-with-alpha: the codebase has no WebP precedent
    anywhere (photo renditions and flyer thumbs are JPEG),
    and at logo widths a flat-color mark compresses to a
    few KB as PNG without a second encoder flavor to tune.
  * SVG. Harvested brand marks may be SVG (five of the
    seeded directory logos are). SVG is already optimal —
    resolution-independent and small — and Pillow cannot
    rasterize it. SVG keys get NO variant, ever: callers
    serve the original, which for an SVG is the right bytes.

Opaque sources (JPEGs, and PNGs whose alpha channel turns
out fully opaque) keep the EXISTING photo path: the variant
is thumbs.rendition's JPEG, the site's one rendition flavor,
byte for byte.

Like the photo pipeline, a rendition is a cache of its
original under a derived key — stored back into object
storage, existence is the cache test, originals are never
modified — and it is generated lazily on first read so a
freshly harvested (or personally-set) logo heals itself
without waiting for the backfill script. A source that
can't be decoded yields no variant and callers serve the
original, with one guard the photo pipeline doesn't need:
logo resolution happens inside serializers, not an image
endpoint, so a failed generation is remembered in-process
for an hour instead of being re-fetched and re-failed on
every directory render. (A logo replaced under the same
key heals on the next process start or backfill run.)
"""

import io
import time

from app.core.storage import storage
from app.modules.inventory import thumbs

# (key, width) -> monotonic time of the last failed
# generation attempt. Process-local on purpose: it exists
# to keep one undecodable logo from taxing every read,
# not to be a durable record.
_FAILED: dict[tuple[str, int], float] = {}
_FAILED_TTL_SECONDS = 3600


def is_svg_key(key: str) -> bool:
    """SVG sources pass through untouched (see module
    docstring): they never have a variant."""
    return key.lower().endswith(".svg")


def alpha_variant_key(key: str, width: int) -> str:
    """The derived key an alpha-preserving rendition lives
    under — thumbs' scheme with the PNG extension."""
    return f"{key}.thumb{width}.png"


def _candidate_keys(key: str, width: int) -> list[str]:
    """Derived keys a variant for `key` may live under, most
    likely first. The flavor is chosen at generation from
    the DECODED pixels (real alpha -> PNG, opaque -> JPEG),
    which serve time can't know without decoding the whole
    original — so it probes both, ordered by the source's
    own extension: PNG/WebP/GIF sources are the
    alpha-capable harvest formats, JPEG sources never carry
    alpha."""
    png = alpha_variant_key(key, width)
    jpg = thumbs.variant_key(key, width)
    if key.lower().endswith((".jpg", ".jpeg")):
        return [jpg, png]
    return [png, jpg]


def existing_variant_key(key: str, width: int) -> str | None:
    """The derived key of the variant already in storage
    for `key` at `width`, or None. SVG keys never have
    one. Never raises — a storage problem reads as "no
    variant", and callers serve the original."""
    if is_svg_key(key):
        return None
    for candidate in _candidate_keys(key, width):
        try:
            storage.head(candidate)
            return candidate
        except Exception:
            continue
    return None


def variant_exists(key: str, width: int) -> bool:
    return existing_variant_key(key, width) is not None


def _real_alpha(image) -> bool:  # noqa: ANN001 — a PIL Image
    """True when the decoded image carries transparency
    that would actually show: an alpha channel (or palette
    transparency) with at least one not-fully-opaque pixel.
    An RGBA file whose alpha is uniformly 255 is opaque for
    rendition purposes and takes the smaller JPEG path."""
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        return image.convert("RGBA").getchannel("A").getextrema()[0] < 255
    return False


def generate(key: str, width: int) -> str | None:
    """Make the variant for `key` at `width` now and return
    its derived key; None when no variant can or should
    exist (SVG, missing original, undecodable bytes).
    Never raises; never touches the original."""
    if is_svg_key(key):
        return None
    existing = existing_variant_key(key, width)
    if existing is not None:
        return existing
    try:
        original = storage.fetch(key)
    except Exception:
        return None
    alpha_bytes: bytes | None = None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(original)) as image:
            image.load()
            if _real_alpha(image):
                rgba = image.convert("RGBA")
                rgba.thumbnail((width, width))
                out = io.BytesIO()
                rgba.save(out, "PNG")
                alpha_bytes = out.getvalue()
    except Exception:
        return None
    if alpha_bytes is not None:
        vkey = alpha_variant_key(key, width)
        try:
            storage.put_bytes(vkey, alpha_bytes, "image/png")
            storage.head(vkey)
            return vkey
        except Exception:
            return None
    # Opaque: the photo pipeline's JPEG, unchanged — the
    # shared generator fetches, flattens, re-encodes and
    # caches under the .jpg derived key itself.
    if thumbs.rendition(key, width) is not None:
        return thumbs.variant_key(key, width)
    return None


def rendition(key: str, width: int) -> str | None:
    """The derived key to serve for `key` at `width`: the
    cached variant when one exists, generated on this
    first read otherwise; None means "serve the original"
    (SVG, undecodable, storage trouble). Never raises."""
    try:
        existing = existing_variant_key(key, width)
        if existing is not None:
            return existing
        if is_svg_key(key):
            return None
        failed_at = _FAILED.get((key, width))
        if (
            failed_at is not None
            and time.monotonic() - failed_at < _FAILED_TTL_SECONDS
        ):
            return None
        made = generate(key, width)
        if made is None:
            _FAILED[(key, width)] = time.monotonic()
        return made
    except Exception:
        return None
