"""Wishlist photo uploads.

The shared attachment machinery, photo kind only — the same
presigned-URL flow inventory's records use (bytes never touch the
API or the database), modeled on the parts module's flow:

  1. issue_upload_url(): validates + returns a short-lived PUT URL
     and the storage key ({owner}/wishlist/{item_id}/photo/...).
  2. Client PUTs the file directly to object storage.
  3. attach_file(): HEADs the object to verify it really exists and
     checks the REAL size/content-type, confirms the key belongs to
     this item + owner, then appends the key to the item.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import ALLOWED_CONTENT_TYPES, StorageError, storage
from app.modules.wishlist import models, schemas

MAX_BYTES = settings.upload_max_mb * 1024 * 1024


class WishlistUploadError(ValueError):
    """Caller turns this into a 4xx."""


def _get_item(
    db: Session, owner_id: uuid.UUID, item_id: uuid.UUID
) -> models.WishlistItem:
    item = db.get(models.WishlistItem, item_id)
    if item is None or item.owner_id != owner_id:
        raise WishlistUploadError("Wishlist item not found")
    return item


def issue_upload_url(
    db: Session,
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
) -> schemas.UploadUrlResponse:
    _get_item(db, owner_id, item_id)
    if payload.kind != "photo":
        raise WishlistUploadError("Wishlist items carry photos only.")
    content_type = payload.content_type.lower().strip()
    if content_type not in ALLOWED_CONTENT_TYPES["photo"]:
        raise WishlistUploadError(
            f"content_type '{payload.content_type}' not allowed for photo"
        )
    if payload.size_bytes is not None:
        if payload.size_bytes <= 0:
            raise WishlistUploadError("size_bytes must be positive")
        if payload.size_bytes > MAX_BYTES:
            raise WishlistUploadError(
                f"File too large: {payload.size_bytes} bytes "
                f"(max {MAX_BYTES // (1024 * 1024)} MB)"
            )
    key = storage.object_key(
        str(owner_id), str(item_id), "photo", payload.filename,
        collection="wishlist",
    )
    try:
        url = storage.presigned_put_url(key, content_type)
    except StorageError as exc:
        raise WishlistUploadError(str(exc)) from exc
    return schemas.UploadUrlResponse(upload_url=url, key=key, expires_in=900)


def attach_file(
    db: Session,
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: schemas.AttachRequest,
) -> dict:
    """Verify the uploaded object and attach its key to the item."""
    item = _get_item(db, owner_id, item_id)

    expected_prefix = f"{owner_id}/wishlist/{item_id}/"
    if not payload.key.startswith(expected_prefix):
        raise WishlistUploadError("Storage key does not belong to this item")

    try:
        stored = storage.head(payload.key)
    except StorageError as exc:
        raise WishlistUploadError(str(exc)) from exc

    if stored.size_bytes > MAX_BYTES:
        raise WishlistUploadError(
            f"File too large: {stored.size_bytes} bytes "
            f"(max {MAX_BYTES // (1024 * 1024)} MB)"
        )
    if stored.content_type not in ALLOWED_CONTENT_TYPES["photo"]:
        raise WishlistUploadError(
            f"Uploaded content type '{stored.content_type}' not allowed for photo"
        )
    # Content sniff (deep audit F4-06): bytes must match the declared
    # image type, not just claim it.
    try:
        storage.verify_content_matches(payload.key, stored.content_type)
    except StorageError as exc:
        raise WishlistUploadError(str(exc)) from exc

    attachment = {
        "key": stored.key,
        "filename": payload.filename or storage.safe_filename(payload.key),
        "kind": "photo",
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    item.attachments = [*item.attachments, attachment]
    db.commit()
    db.refresh(item)
    return attachment
