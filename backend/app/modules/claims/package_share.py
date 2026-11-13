"""Claim package sharing (audit A10, 2026-10-22).

The package PDF gains two outbound paths beyond download:

  - "Save to my Drive" — uploads the PDF through the owner's
    Wave-4 Google Drive connection (core.cloud_backup), into a
    "Toolbox Vault Claim Packages" folder. No connection -> a
    plain refusal the page turns into a connect prompt.
  - "Email the package" — sends through the email seam
    (app.core.notifications.send_email) with the PDF attached.
    Over the attachment cap the email carries the Drive link
    instead: the package is saved to Drive first (same refusal
    if Drive isn't connected) — the file is NEVER silently
    dropped.

Both actions are journaled the claims-native way: a system entry
in the claim's own communications log (which later packages
include), and the email itself lands in the mail outbox via the
seam. The change journal captures the comm-row creation like
every other claim edit.
"""

import uuid

from sqlalchemy.orm import Session

from app.core import notifications
from app.modules.claims import models, package as package_module, service
from app.modules.core import cloud_backup
from app.modules.core import models as core_models

# A sane attachment cap: generous for a photo-bearing package,
# well inside provider limits (Resend caps a message at 40 MB).
MAX_EMAIL_ATTACHMENT_BYTES = 10 * 1024 * 1024
PACKAGES_FOLDER = "Toolbox Vault Claim Packages"
EMAIL_KIND = "claim_package"


class DriveNotConnected(service.ClaimsError):
    """The owner has no Google Drive connection — the page
    offers the connect flow for this one."""


def _journal_entry(
    db: Session, owner: core_models.User, claim: models.Claim, summary: str
) -> None:
    """A system comm-log entry: the claim's own record that the
    package left the building, and how. Written directly (not
    via add_communication) because a share of a CLOSED claim is
    still worth recording — the open-check guards the owner's
    correspondence edits, not the system's bookkeeping."""
    db.add(
        models.ClaimCommunication(
            owner_id=owner.id,
            claim_id=claim.id,
            channel="system",
            contact="",
            summary=summary,
            occurred_at=service._now(),
        )
    )
    db.commit()


def _drive_save(
    db: Session, owner: core_models.User, claim: models.Claim, content: bytes
) -> dict:
    connection = cloud_backup.connection_for(db, owner.id)
    if connection is None:
        raise DriveNotConnected(
            "Google Drive isn't connected yet — connect it to save "
            "the package there."
        )
    client = cloud_backup.drive_client_for(db, connection)
    folder = client.ensure_folder(PACKAGES_FOLDER)
    filename = f"claim-package-{claim.claim_number}.pdf"
    result = client.upload(
        filename, str(folder.get("id") or ""), content, mime_type="application/pdf"
    )
    return {
        "filename": filename,
        "drive_file_id": str(result.get("id") or ""),
        "drive_link": str(result.get("webViewLink") or ""),
    }


def save_package_to_drive(
    db: Session, owner: core_models.User, claim_id: uuid.UUID
) -> dict:
    claim = service.get_claim(db, owner, claim_id)
    content = package_module.build_package(db, owner, claim)
    saved = _drive_save(db, owner, claim, content)
    _journal_entry(
        db,
        owner,
        claim,
        f"Claim package saved to Google Drive ({saved['filename']}).",
    )
    return {**saved, "emailed": False, "via": "drive"}


def email_package(
    db: Session, owner: core_models.User, claim_id: uuid.UUID
) -> dict:
    claim = service.get_claim(db, owner, claim_id)
    content = package_module.build_package(db, owner, claim)
    filename = f"claim-package-{claim.claim_number}.pdf"
    subject = f"Claim package — {claim.claim_number}"
    if len(content) <= MAX_EMAIL_ATTACHMENT_BYTES:
        sent = notifications.send_email(
            db,
            owner.email,
            subject,
            (
                f"Your claim package for {claim.claim_number} is "
                "attached as a PDF — the same document the Download "
                "button produces, ready to hand to your insurer."
            ),
            kind=EMAIL_KIND,
            attachment=(filename, content),
        )
        if not sent:
            raise service.ClaimsError(
                "The email couldn't be sent — email delivery isn't "
                "available right now. Download the package instead."
            )
        _journal_entry(
            db, owner, claim, f"Claim package emailed to {owner.email} (PDF attached)."
        )
        return {"filename": filename, "emailed": True, "via": "attachment"}
    # Oversized: save to Drive and email the link instead — the
    # package itself never silently vanishes.
    saved = _drive_save(db, owner, claim, content)
    link = saved["drive_link"] or "(open Google Drive to find it)"
    sent = notifications.send_email(
        db,
        owner.email,
        subject,
        (
            f"Your claim package for {claim.claim_number} is too "
            "large to attach to an email, so it was saved to your "
            f"Google Drive instead: {link}"
        ),
        kind=EMAIL_KIND,
    )
    if not sent:
        raise service.ClaimsError(
            "The email couldn't be sent — email delivery isn't "
            "available right now. The package is saved in your "
            "Google Drive."
        )
    _journal_entry(
        db,
        owner,
        claim,
        "Claim package was too large to email — saved to Google "
        "Drive and the link emailed instead.",
    )
    return {**saved, "emailed": True, "via": "drive_link"}
