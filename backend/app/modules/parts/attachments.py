"""Part photo uploads (parts module).

The shared attachment machinery, photo kind only — the same
presigned-URL flow inventory's records use (bytes never touch the
API or the database):

  1. issue_upload_url(): validates + returns a short-lived PUT URL
     and the storage key ({owner}/parts/{part_id}/photo/...).
  2. Client PUTs the file directly to object storage.
  3. attach_file(): HEADs the object to verify it really exists and
     checks the REAL size/content-type, confirms the key belongs to
     this part + owner, then appends the key to the part.

Modeled on the dealers portal's profile-photo flow (the precedent
for a non-inventory module riding the shared machinery): inventory's
own attachments module stays inventory's.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import ALLOWED_CONTENT_TYPES, StorageError, storage
from app.modules.parts import models, schemas

MAX_BYTES = settings.upload_max_mb * 1024 * 1024


class PartUploadError(ValueError):
    """Caller turns this into a 4xx."""


def _get_part(db: Session, owner_id: uuid.UUID, part_id: uuid.UUID) -> models.Part:
    part = db.get(models.Part, part_id)
    if part is None or part.owner_id != owner_id:
        raise PartUploadError("Part not found")
    return part


def issue_upload_url(
    db: Session,
    owner_id: uuid.UUID,
    part_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
) -> schemas.UploadUrlResponse:
    _get_part(db, owner_id, part_id)
    if payload.kind != "photo":
        raise PartUploadError("Parts carry photos only.")
    content_type = payload.content_type.lower().strip()
    if content_type not in ALLOWED_CONTENT_TYPES["photo"]:
        raise PartUploadError(
            f"content_type '{payload.content_type}' not allowed for photo"
        )
    if payload.size_bytes is not None:
        if payload.size_bytes <= 0:
            raise PartUploadError("size_bytes must be positive")
        if payload.size_bytes > MAX_BYTES:
            raise PartUploadError(
                f"File too large: {payload.size_bytes} bytes "
                f"(max {MAX_BYTES // (1024 * 1024)} MB)"
            )
    key = storage.object_key(
        str(owner_id), str(part_id), "photo", payload.filename, collection="parts"
    )
    try:
        url = storage.presigned_put_url(key, content_type)
    except StorageError as exc:
        raise PartUploadError(str(exc)) from exc
    return schemas.UploadUrlResponse(upload_url=url, key=key, expires_in=900)


def attach_file(
    db: Session,
    owner_id: uuid.UUID,
    part_id: uuid.UUID,
    payload: schemas.AttachRequest,
) -> dict:
    """Verify the uploaded object and attach its key to the part."""
    part = _get_part(db, owner_id, part_id)

    expected_prefix = f"{owner_id}/parts/{part_id}/"
    if not payload.key.startswith(expected_prefix):
        raise PartUploadError("Storage key does not belong to this part")

    try:
        stored = storage.head(payload.key)
    except StorageError as exc:
        raise PartUploadError(str(exc)) from exc

    if stored.size_bytes > MAX_BYTES:
        raise PartUploadError(
            f"File too large: {stored.size_bytes} bytes "
            f"(max {MAX_BYTES // (1024 * 1024)} MB)"
        )
    if stored.content_type not in ALLOWED_CONTENT_TYPES["photo"]:
        raise PartUploadError(
            f"Uploaded content type '{stored.content_type}' not allowed for photo"
        )
    # Content sniff (deep audit F4-06): bytes must match the declared
    # image type, not just claim it.
    try:
        storage.verify_content_matches(payload.key, stored.content_type)
    except StorageError as exc:
        raise PartUploadError(str(exc)) from exc

    attachment = {
        "key": stored.key,
        "filename": payload.filename or storage.safe_filename(payload.key),
        "kind": "photo",
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    part.attachments = [*part.attachments, attachment]
    db.commit()
    db.refresh(part)
    return attachment


def delete_part_files(part: models.Part) -> None:
    """Best-effort cleanup of a deleted part's photo objects. Never
    raises (same contract as inventory's delete_record_files)."""
    for item in part.attachments or []:
        key = item.get("key") if isinstance(item, dict) else None
        if key:
            try:
                storage.delete(key)
            except StorageError:
                continue  # orphaned keys are harmless; bucket lifecycle ages them


def copy_photo_for_tool(
    owner_id: uuid.UUID, tool_id: uuid.UUID, attachment: dict
) -> str:
    """Copy one of a part's photo objects into a tool's namespace
    ({owner}/tools/{tool_id}/photo/...) for the convert-to-tool
    flow, returning the NEW key. The caller hands the key to
    inventory's own attach flow, which verifies and appends it —
    parts never writes a tool row.

    The key MUST move namespaces: parts delete their own objects,
    and a converted tool's photos have to live and die with the
    tool, never with the part it was copied from."""
    source_key = attachment["key"]
    filename = attachment.get("filename") or storage.safe_filename(source_key)
    dest_key = storage.object_key(
        str(owner_id), str(tool_id), "photo", filename, collection="tools"
    )
    storage.copy(source_key, dest_key)
    return dest_key
