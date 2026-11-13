"""Photo/document/receipt uploads (inventory module).

Presigned-URL flow — bytes never touch the API or the database:

  1. issue_upload_url(): validates kind + content type + declared size,
     returns a short-lived PUT URL and the storage key.
  2. Client PUTs the file directly to object storage.
  3. attach_file(): HEADs the object to verify it really exists and checks
     the REAL size/content-type (not just what the client claimed), confirms
     the key belongs to this record+owner, then appends the key to it.

Only keys (+ metadata) are stored on the record. Read URLs are minted
fresh by serialize in service.py because presigned URLs expire.

Records come in two collections — 'tools' and 'batteries' — and the
flow is identical for both; `collection` picks the model and the
storage-key namespace ({owner}/tools/{id}/… vs {owner}/batteries/{id}/…).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import ALLOWED_CONTENT_TYPES, StorageError, storage
from app.modules.inventory import models, schemas

MAX_BYTES = settings.upload_max_mb * 1024 * 1024

# Documents and receipts may be bigger than photos (a scanned manual
# or a multi-page invoice PDF): 25 MB for the document/receipt kinds,
# while photos keep the configured photo limit (owner clarification,
# 2026-10-18 — the cap follows the KIND, whatever the file type).
DOCUMENT_MAX_BYTES = 25 * 1024 * 1024


def max_bytes_for(kind: str) -> int:
    """The size cap for one attachment kind."""
    return MAX_BYTES if kind == "photo" else DOCUMENT_MAX_BYTES


# collection -> (model, singular label for error copy). Set pieces
# carry attachments too (a photo of the broken socket, its receipt):
# namespace {owner}/pieces/{piece_id}/... Maintenance LOG ENTRIES
# joined in Package B (calibration certificates for a service
# event): namespace {owner}/log_entries/{entry_id}/... — the
# maintenance module's routes drive this same flow; the entry model
# is imported lazily here to keep the module graph one-directional.
def _collections() -> dict:
    from app.modules.maintenance import models as maintenance_models

    return {
        "tools": (models.Tool, "Tool"),
        "batteries": (models.Battery, "Battery"),
        "pieces": (models.SetPiece, "Set piece"),
        "log_entries": (maintenance_models.MaintenanceLogEntry, "Log entry"),
    }


class UploadError(ValueError):
    """Caller turns this into a 4xx."""


class RecordNotFound(UploadError):
    """The target record doesn't exist (or isn't the caller's).
    Routes answer 404 for this subclass — every sibling endpoint
    uses 404 for a missing record, and the upload routes answering
    422 for it was an inconsistency (deep audit F4-03, folded nit)."""


def _too_large(size_bytes: int, kind: str) -> UploadError:
    cap = max_bytes_for(kind)
    return UploadError(
        f"File too large: {size_bytes} bytes (max {cap // (1024 * 1024)} MB)"
    )


def _get_record(
    db: Session, owner_id: uuid.UUID, item_id: uuid.UUID, collection: str
):
    model, label = _collections()[collection]
    record = db.get(model, item_id)
    if record is None or record.owner_id != owner_id:
        raise RecordNotFound(f"{label} not found")
    return record


def issue_upload_url(
    db: Session,
    owner_id: uuid.UUID,
    tool_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
    collection: str = "tools",
) -> schemas.UploadUrlResponse:
    _get_record(db, owner_id, tool_id, collection)
    kind = payload.kind
    if kind not in ALLOWED_CONTENT_TYPES:
        raise UploadError(f"kind must be one of {sorted(ALLOWED_CONTENT_TYPES)}")
    content_type = payload.content_type.lower().strip()
    if content_type not in ALLOWED_CONTENT_TYPES[kind]:
        raise UploadError(
            f"content_type '{payload.content_type}' not allowed for {kind}"
        )
    if payload.size_bytes is not None:
        if payload.size_bytes <= 0:
            raise UploadError("size_bytes must be positive")
        if payload.size_bytes > max_bytes_for(kind):
            raise _too_large(payload.size_bytes, kind)
    key = storage.object_key(
        str(owner_id), str(tool_id), kind, payload.filename, collection=collection
    )
    try:
        url = storage.presigned_put_url(key, content_type)
    except StorageError as exc:
        raise UploadError(str(exc)) from exc
    return schemas.UploadUrlResponse(upload_url=url, key=key, expires_in=900)


def attach_file(
    db: Session,
    owner_id: uuid.UUID,
    tool_id: uuid.UUID,
    payload: schemas.AttachRequest,
    collection: str = "tools",
) -> dict:
    """Verify the uploaded object and attach its key to the record."""
    record = _get_record(db, owner_id, tool_id, collection)
    _, label = _collections()[collection]

    expected_prefix = f"{owner_id}/{collection}/{tool_id}/"
    if not payload.key.startswith(expected_prefix):
        raise UploadError(f"Storage key does not belong to this {label.lower()}")

    try:
        stored = storage.head(payload.key)
    except StorageError as exc:
        raise UploadError(str(exc)) from exc

    kind = payload.key.split("/")[3]  # {owner}/{collection}/{id}/{kind}/...
    if stored.size_bytes > max_bytes_for(kind):
        raise _too_large(stored.size_bytes, kind)
    if stored.content_type not in ALLOWED_CONTENT_TYPES.get(kind, set()):
        raise UploadError(
            f"Uploaded content type '{stored.content_type}' not allowed for {kind}"
        )
    # Content sniff (deep audit F4-06): the declared type was bound by
    # the PUT signature and read back by HEAD, but the BYTES were
    # never inspected — an HTML file declared as image/png attached
    # cleanly. Verify the magic bytes against the declared type.
    try:
        storage.verify_content_matches(payload.key, stored.content_type)
    except StorageError as exc:
        raise UploadError(str(exc)) from exc

    # Police-report documents (2026-10-25): a file may be tied to
    # one of THIS item's lost/stolen reports. The report must be
    # the caller's and must hang off this very record — anything
    # else is refused, so a report's documents can never point at
    # another item's (or another user's) paper trail.
    loss_report_id = getattr(payload, "loss_report_id", None)
    if loss_report_id is not None:
        expected_kind = {"tools": "tool", "batteries": "battery"}.get(collection)
        report = db.get(models.ItemLossReport, loss_report_id)
        if (
            report is None
            or report.owner_id != owner_id
            or report.item_id != record.id
            or expected_kind is None
            or report.item_kind != expected_kind
        ):
            raise UploadError("That report doesn't belong to this item.")

    attachment = {
        "key": stored.key,
        "filename": payload.filename or storage.safe_filename(payload.key),
        "kind": kind,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    if loss_report_id is not None:
        attachment["loss_report_id"] = str(loss_report_id)
    record.attachments = [*record.attachments, attachment]
    db.commit()
    db.refresh(record)
    return attachment


def delete_attachment(
    db: Session,
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    key: str,
    collection: str = "tools",
) -> dict:
    """Remove ONE attachment from a record (deep audit F1-31,
    surfaced by Round A, built in Round F): the row comes off the
    record AND the object is deleted from storage. Owner-scoped
    through _get_record — another user's record is a 404, and a
    key that is not one of THAT record's attachments is a 404 too
    (never a cross-record delete). Storage deletion happens after
    the row commit; a storage failure leaves an orphaned object
    (harmless, bucket lifecycle ages it) rather than a record that
    still points at a deleted file."""
    record = _get_record(db, owner_id, item_id, collection)
    entry = next(
        (
            item
            for item in record.attachments or []
            if isinstance(item, dict) and item.get("key") == key
        ),
        None,
    )
    if entry is None:
        raise RecordNotFound("Attachment not found")
    record.attachments = [
        item
        for item in record.attachments or []
        if not (isinstance(item, dict) and item.get("key") == key)
    ]
    db.commit()
    try:
        storage.delete(key)
    except StorageError:
        pass  # orphaned keys are harmless; see delete_record_files
    return {"deleted": True, "key": key, "kind": entry.get("kind", "")}


def delete_record_files(record) -> None:
    """Best-effort cleanup of a deleted record's objects (tool or
    battery — both carry the same attachments shape). Never raises.

    NOTE (audit trail, 2026-10-19): the delete paths no longer call
    this — deleting a record TOMBSTONES its files through core's
    journal (retained for the retention window so a restore brings
    the photos back; account deletion still destroys bytes, via
    the journal's permanent mode inside retire_record_files)."""
    for item in record.attachments or []:
        key = item.get("key") if isinstance(item, dict) else None
        if key:
            try:
                storage.delete(key)
            except StorageError:
                continue  # orphaned keys are harmless; bucket lifecycle can age them


class EmailRateLimited(UploadError):
    """The sender exhausted the "Email this file" budget. Carries
    the retry delay so the route can answer a proper 429."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            f"Too many emailed files — try again in {retry_after} seconds."
        )
        self.retry_after = retry_after


def send_attachment_email(
    db: Session,
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    collection: str,
    *,
    key: str,
    recipient: str,
    sender_name: str,
    item_name: str,
) -> dict:
    """The AttachmentViewer's "Email this file" action.

    Owner-scoped by construction: the record resolves through
    _get_record (another user's item id is a 404-shaped refusal) and
    the key must be one of THAT record's stored attachments — a key
    from anywhere else is refused. The file bytes are read through
    the storage service and capped at the kind's upload limit before
    they ride the email seam (which records an outbox row noting the
    attachment)."""
    from app.core import notifications
    from app.core.rate_limit import attachment_email_rate_limiter

    record = _get_record(db, owner_id, item_id, collection)
    entry = next(
        (
            item
            for item in record.attachments or []
            if isinstance(item, dict) and item.get("key") == key
        ),
        None,
    )
    if entry is None:
        raise UploadError("That file isn't attached to this item.")
    kind = entry.get("kind", "")
    if kind not in ALLOWED_CONTENT_TYPES:
        raise UploadError("That file can't be emailed.")

    retry_after = attachment_email_rate_limiter.retry_after(str(owner_id))
    if retry_after is not None:
        raise EmailRateLimited(retry_after)

    try:
        content = storage.fetch(key)
    except StorageError as exc:
        raise UploadError(f"Couldn't read the file from storage: {exc}") from exc
    if len(content) > max_bytes_for(kind):
        raise _too_large(len(content), kind)

    filename = entry.get("filename") or storage.safe_filename(key)
    attachment_email_rate_limiter.record_hit(str(owner_id))
    sent = notifications.send_email(
        db,
        recipient,
        f"{sender_name} sent you a file from Toolbox Vault: {filename}",
        (
            f"{sender_name} shared a file from their Toolbox Vault "
            f"inventory with you.\n\n"
            f"Item: {item_name}\n"
            f"File: {filename}\n\n"
            "The file is attached to this message."
        ),
        kind=notifications.KIND_ATTACHMENT_SHARE,
        attachment=(filename, content),
    )
    return {"sent": sent, "filename": filename, "kind": kind, "recipient": recipient}
