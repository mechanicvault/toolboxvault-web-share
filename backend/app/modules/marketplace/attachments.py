"""Listing photo uploads (marketplace module).

The shared attachment machinery, photo kind only — the same
presigned-URL flow parts use (bytes never touch the API or the
database), keyed {owner}/marketplace/{listing_id}/photo/... :

  1. issue_upload_url(): validates + returns a short-lived PUT
     URL and the storage key.
  2. Client PUTs the file directly to object storage.
  3. attach_file(): HEADs the object to verify it really exists
     and checks the REAL size/content-type, confirms the key
     belongs to this listing + owner, then appends the key.

Modeled directly on the parts module's attachments.py (the
precedent for a non-inventory module riding the shared
machinery): inventory's own attachments module stays inventory's.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import ALLOWED_CONTENT_TYPES, StorageError, storage
from app.modules.marketplace import models, schemas

MAX_BYTES = settings.upload_max_mb * 1024 * 1024


class ListingUploadError(ValueError):
    """Caller turns this into a 4xx."""


def _get_listing(
    db: Session, owner_id: uuid.UUID, listing_id: uuid.UUID
) -> models.SaleListing:
    listing = db.get(models.SaleListing, listing_id)
    if listing is None or listing.owner_id != owner_id:
        raise ListingUploadError("Listing not found")
    return listing


def issue_upload_url(
    db: Session,
    owner_id: uuid.UUID,
    listing_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
) -> schemas.UploadUrlResponse:
    _get_listing(db, owner_id, listing_id)
    if payload.kind != "photo":
        raise ListingUploadError("Listings carry photos only.")
    content_type = payload.content_type.lower().strip()
    if content_type not in ALLOWED_CONTENT_TYPES["photo"]:
        raise ListingUploadError(
            f"content_type '{payload.content_type}' not allowed for photo"
        )
    if payload.size_bytes is not None:
        if payload.size_bytes <= 0:
            raise ListingUploadError("size_bytes must be positive")
        if payload.size_bytes > MAX_BYTES:
            raise ListingUploadError(
                f"File too large: {payload.size_bytes} bytes "
                f"(max {MAX_BYTES // (1024 * 1024)} MB)"
            )
    key = storage.object_key(
        str(owner_id), str(listing_id), "photo", payload.filename,
        collection="marketplace",
    )
    try:
        url = storage.presigned_put_url(key, content_type)
    except StorageError as exc:
        raise ListingUploadError(str(exc)) from exc
    return schemas.UploadUrlResponse(upload_url=url, key=key, expires_in=900)


def attach_file(
    db: Session,
    owner_id: uuid.UUID,
    listing_id: uuid.UUID,
    payload: schemas.AttachRequest,
) -> dict:
    """Verify the uploaded object and attach its key to the listing."""
    listing = _get_listing(db, owner_id, listing_id)

    expected_prefix = f"{owner_id}/marketplace/{listing_id}/"
    if not payload.key.startswith(expected_prefix):
        raise ListingUploadError("Storage key does not belong to this listing")

    try:
        stored = storage.head(payload.key)
    except StorageError as exc:
        raise ListingUploadError(str(exc)) from exc

    if stored.size_bytes > MAX_BYTES:
        raise ListingUploadError(
            f"File too large: {stored.size_bytes} bytes "
            f"(max {MAX_BYTES // (1024 * 1024)} MB)"
        )
    if stored.content_type not in ALLOWED_CONTENT_TYPES["photo"]:
        raise ListingUploadError(
            f"Uploaded content type '{stored.content_type}' not allowed for photo"
        )
    # Content sniff (deep audit F4-06): bytes must match the declared
    # image type, not just claim it.
    try:
        storage.verify_content_matches(payload.key, stored.content_type)
    except StorageError as exc:
        raise ListingUploadError(str(exc)) from exc

    attachment = {
        "key": stored.key,
        "filename": payload.filename or storage.safe_filename(payload.key),
        "kind": "photo",
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    listing.attachments = [*listing.attachments, attachment]
    db.commit()
    db.refresh(listing)
    return attachment

