"""Size-appropriate photo renditions for list/tile slots (F3-12/F1-05).

Originals are phone photos (often 3-8 MB) but inventory tiles render
at ~320px and list rows at ~128px. Serving the original into those
slots was the bandwidth/decode cost. The mechanism chosen is the
smallest honest one for this stack:

  * Renditions are generated ON FIRST READ by this module (Pillow
    thumbnail, JPEG re-encode), then stored back into object storage
    under a derived key (`<key>.thumb<width>.jpg`) — so every later
    read is a plain storage fetch, cache-friendly end to end, and
    photos uploaded before this feature existed gain renditions
    lazily with no migration or backfill job.
  * Access rides a capability URL, the same security model as the
    existing 7-day presigned GET URLs: an HMAC (keyed with the JWT
    secret, which never leaves the server) over key+width+expiry.
    The serializer mints a fresh signed URL on every read, exactly
    like it mints fresh presigned URLs; an expired or forged
    signature is a 404, never a leak of another owner's key space.
"""

import hashlib
import hmac
import io
import time
from urllib.parse import quote

from app.core.config import settings
from app.core.storage import StorageError, storage

# The only rendition widths that exist. Tile slots want 320, list
# rows 128 — anything else is refused so the endpoint can't be used
# as a general image proxy/resizer.
WIDTHS = (128, 320)
_TTL_SECONDS = 604800  # 7 days, matching presigned GET URLs


def _signature(key: str, width: int, expires: int) -> str:
    msg = f"thumb:{width}:{expires}:{key}".encode()
    return hmac.new(
        settings.jwt_secret.encode(), msg, hashlib.sha256
    ).hexdigest()


def signed_thumb_url(key: str, width: int) -> str:
    """A fresh signed rendition URL for one stored photo key."""
    expires = int(time.time()) + _TTL_SECONDS
    sig = _signature(key, width, expires)
    return (
        f"/api/inventory/thumb/{width}"
        f"?k={quote(key, safe='')}&e={expires}&s={sig}"
    )


def verify(key: str, width: int, expires: int, sig: str) -> bool:
    if width not in WIDTHS:
        return False
    if expires < int(time.time()):
        return False
    return hmac.compare_digest(_signature(key, width, expires), sig or "")


def variant_key(key: str, width: int) -> str:
    return f"{key}.thumb{width}.jpg"


def rendition(key: str, width: int) -> bytes | None:
    """The rendition bytes for `key` at `width`, generating and
    caching the variant in storage on first read. None when the
    original isn't a decodable image (callers answer 404)."""
    vkey = variant_key(key, width)
    try:
        return storage.fetch(vkey)
    except StorageError:
        pass  # not generated yet — fall through and make it
    try:
        original = storage.fetch(key)
    except StorageError:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(original)) as image:
            image = image.convert("RGB")
            image.thumbnail((width, width))
            out = io.BytesIO()
            image.save(out, "JPEG", quality=78)
            data = out.getvalue()
    except Exception:
        return None
    try:
        storage.put_bytes(vkey, data, "image/jpeg")
    except StorageError:
        pass  # serving this read matters more than caching the next
    return data
