"""Disaster Claims HTTP surface — INSURANCE claims only (claims
separation, 2026-11-05). Thin: parse, gate, call the service, map
errors. All business rules live in the claims module's service.py,
kind-scoped: every route here resolves claims through the
INSURANCE kind scope, so a warranty claim addressed here is a
404, exactly like a stranger's claim — and the warranty Claims
surface (/api/claims) answers insurance claims the same way.

The insurance claim is a ONE-party record: the owner and their
insurer (off-platform). There is no second seat here — the
warranty claim's agent seat lives in the claims module and never
applies to a disaster claim.

Gated by the module-control system on THIS module
(disaster_claims; rollout mirrors the claims module's): a user
whose groups don't include it gets 403 {code:
module_unavailable} here, and the section's menu item, home
widget and search group ride the same switch.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.modules.claims import models as claim_models
from app.modules.claims import schemas, service

router = APIRouter(tags=["disaster_claims"])

_disaster_module = require_module("disaster_claims")

_INSURANCE = claim_models.KIND_INSURANCE


def _as_http(exc: service.ClaimsError) -> HTTPException:
    if isinstance(exc, service.ClaimsNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/stats", response_model=schemas.ClaimsStats)
def disaster_stats(
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    return service.stats(db, user.id, _INSURANCE)


@router.get("/targets", response_model=schemas.TargetsView)
def disaster_targets(
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    """The filing wizard's picker: the owner's assets with the
    values a line can price from and the attachments evidence
    can use."""
    return service.list_targets(db, user)


@router.get("", response_model=list[schemas.ClaimSummary])
def list_disaster_claims(
    include_archived: bool = False,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    claims = service.list_claims(
        db, user, include_archived=include_archived, kind=_INSURANCE
    )
    # Dealer intermingling: each summary names the dealers the
    # claim touches (through its items' tags) so the list can
    # filter/sort by dealer and link through to the dealer page.
    dealer_map = service.dealers_for_claims(db, user.id, claims)
    summaries = []
    for claim in claims:
        summary = service.claim_summary(db, claim, owner_currency=user.currency)
        summary["dealers"] = dealer_map.get(claim.id, [])
        summaries.append(summary)
    return summaries


@router.post("", response_model=schemas.ClaimView, status_code=201)
def create_disaster_claim(
    payload: schemas.ClaimCreate,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    claim = service.create_claim(db, user, **payload.model_dump())
    return service.claim_view(db, user, claim)


@router.get("/{claim_id}", response_model=schemas.ClaimView)
def get_disaster_claim(
    claim_id: uuid.UUID,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        claim = service.get_claim(db, user, claim_id, kind=_INSURANCE)
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, user, claim)


@router.patch("/{claim_id}", response_model=schemas.ClaimView)
def update_disaster_claim(
    claim_id: uuid.UUID,
    payload: schemas.ClaimUpdate,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        claim = service.update_claim(
            db,
            user,
            claim_id,
            kind=_INSURANCE,
            **payload.model_dump(exclude_unset=True),
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, user, claim)


@router.delete("/{claim_id}", status_code=204)
def delete_disaster_claim(
    claim_id: uuid.UUID,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        deleted = service.delete_claim(db, user, claim_id, kind=_INSURANCE)
    except service.ClaimsError as exc:
        raise _as_http(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Claim not found")


@router.post("/{claim_id}/transition", response_model=schemas.ClaimView)
def transition_disaster_claim(
    claim_id: uuid.UUID,
    payload: schemas.TransitionRequest,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        claim = service.transition(
            db,
            user,
            claim_id,
            payload.to_status,
            repair_sent_to=payload.repair_sent_to,
            repair_cost=payload.repair_cost,
            kind=_INSURANCE,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, user, claim)


@router.post(
    "/{claim_id}/proof-of-loss-sent", response_model=schemas.ClaimView
)
def mark_proof_of_loss_sent(
    claim_id: uuid.UUID,
    payload: schemas.ProofOfLossSentRequest,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        claim = service.mark_proof_of_loss_sent(
            db, user, claim_id, payload.sent_date, kind=_INSURANCE
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, user, claim)


# -- archive, duplicate, package ---------------------------------------------------


@router.post("/{claim_id}/archive", response_model=schemas.ClaimView)
def archive_disaster_claim(
    claim_id: uuid.UUID,
    payload: schemas.ArchiveRequest,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        claim = service.set_archived(
            db, user, claim_id, payload.archived, kind=_INSURANCE
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, user, claim)


@router.post(
    "/{claim_id}/duplicate", response_model=schemas.ClaimView, status_code=201
)
def duplicate_disaster_claim(
    claim_id: uuid.UUID,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        claim = service.duplicate_claim(db, user, claim_id, kind=_INSURANCE)
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, user, claim)


@router.get("/{claim_id}/package")
def disaster_claim_package(
    claim_id: uuid.UUID,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    """The claim package PDF: summary + included items (photos +
    values), evidence list, police block, comms log."""
    from fastapi import Response

    from app.modules.claims import package as package_module
    from app.modules.core import service as core_service

    try:
        claim = service.get_claim(db, user, claim_id, kind=_INSURANCE)
    except service.ClaimsError as exc:
        raise _as_http(exc)
    owner = core_service.get_user_by_id(db, user.id)
    content = package_module.build_package(db, owner, claim)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="claim-package-{claim.claim_number}.pdf"'
            )
        },
    )


@router.post(
    "/{claim_id}/package/drive", response_model=schemas.PackageDriveView
)
def save_package_to_drive(
    claim_id: uuid.UUID,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    """Save the package PDF to the owner's Google Drive.
    Disconnected -> 409 with the connect hint in the detail."""
    from app.modules.claims import package_share
    from app.modules.core import service as core_service

    owner = core_service.get_user_by_id(db, user.id)
    try:
        service.get_claim(db, user, claim_id, kind=_INSURANCE)
        return package_share.save_package_to_drive(db, owner, claim_id)
    except package_share.DriveNotConnected as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except service.ClaimsError as exc:
        raise _as_http(exc)


@router.post(
    "/{claim_id}/package/email", response_model=schemas.PackageEmailView
)
def email_package(
    claim_id: uuid.UUID,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    """Email the package through the mail seam — attached when
    it fits, otherwise saved to Drive with the link emailed (409
    when that fallback needs a connection the owner doesn't
    have)."""
    from app.modules.claims import package_share
    from app.modules.core import service as core_service

    owner = core_service.get_user_by_id(db, user.id)
    try:
        service.get_claim(db, user, claim_id, kind=_INSURANCE)
        return package_share.email_package(db, owner, claim_id)
    except package_share.DriveNotConnected as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except service.ClaimsError as exc:
        raise _as_http(exc)


@router.patch(
    "/{claim_id}/lines/{line_id}/package", response_model=schemas.LineView
)
def set_line_package(
    claim_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: schemas.LinePackageRequest,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.set_line_package(
            db,
            user,
            claim_id,
            line_id,
            payload.include_in_package,
            kind=_INSURANCE,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.line_view(row)


# -- lines -----------------------------------------------------------------------


@router.post(
    "/{claim_id}/lines", response_model=schemas.LineView, status_code=201
)
def add_line(
    claim_id: uuid.UUID,
    payload: schemas.LineCreate,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.add_line(
            db,
            user,
            claim_id,
            target_kind=payload.target_kind,
            target_id=payload.target_id,
            include_addons=payload.include_addons,
            value_basis=payload.value_basis,
            amount=payload.amount,
            kind=_INSURANCE,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.line_view(row)


@router.delete("/{claim_id}/lines/{line_id}", status_code=204)
def remove_line(
    claim_id: uuid.UUID,
    line_id: uuid.UUID,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        removed = service.remove_line(
            db, user, claim_id, line_id, kind=_INSURANCE
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    if not removed:
        raise HTTPException(status_code=404, detail="Claim line not found")


# -- evidence ---------------------------------------------------------------------


@router.post(
    "/{claim_id}/evidence", response_model=schemas.EvidenceView, status_code=201
)
def add_evidence_reference(
    claim_id: uuid.UUID,
    payload: schemas.EvidenceReferenceCreate,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.add_evidence_reference(
            db,
            user,
            claim_id,
            item_kind=payload.item_kind,
            item_id=payload.item_id,
            attachment_key=payload.attachment_key,
            kind=_INSURANCE,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.evidence_view(db, row.owner_id, row)


@router.post(
    "/{claim_id}/evidence/upload-url",
    response_model=schemas.EvidenceUploadUrlView,
)
def evidence_upload_url(
    claim_id: uuid.UUID,
    payload: schemas.EvidenceUploadUrlRequest,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        return service.issue_evidence_upload_url(
            db,
            user,
            claim_id,
            kind=payload.kind,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            claim_kind=_INSURANCE,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)


@router.post(
    "/{claim_id}/evidence/attach",
    response_model=schemas.EvidenceView,
    status_code=201,
)
def attach_evidence_upload(
    claim_id: uuid.UUID,
    payload: schemas.EvidenceAttachRequest,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.attach_evidence_upload(
            db,
            user,
            claim_id,
            key=payload.key,
            filename=payload.filename,
            kind=_INSURANCE,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.evidence_view(db, row.owner_id, row)


@router.delete("/{claim_id}/evidence/{evidence_id}", status_code=204)
def remove_evidence(
    claim_id: uuid.UUID,
    evidence_id: uuid.UUID,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        removed = service.remove_evidence(
            db, user, claim_id, evidence_id, kind=_INSURANCE
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    if not removed:
        raise HTTPException(status_code=404, detail="Evidence not found")


# -- communications log -------------------------------------------------------------


@router.post(
    "/{claim_id}/communications",
    response_model=schemas.CommunicationView,
    status_code=201,
)
def add_communication(
    claim_id: uuid.UUID,
    payload: schemas.CommunicationCreate,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.add_communication(
            db,
            user,
            claim_id,
            channel=payload.channel,
            contact=payload.contact,
            summary=payload.summary,
            occurred_at=payload.occurred_at,
            kind=_INSURANCE,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.comm_view(row)


@router.patch(
    "/{claim_id}/communications/{entry_id}",
    response_model=schemas.CommunicationView,
)
def update_communication(
    claim_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: schemas.CommunicationUpdate,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.update_communication(
            db,
            user,
            claim_id,
            entry_id,
            kind=_INSURANCE,
            **payload.model_dump(exclude_unset=True),
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.comm_view(row)


@router.delete("/{claim_id}/communications/{entry_id}", status_code=204)
def delete_communication(
    claim_id: uuid.UUID,
    entry_id: uuid.UUID,
    user: CurrentUser = Depends(_disaster_module),
    db: Session = Depends(get_db),
):
    try:
        deleted = service.delete_communication(
            db, user, claim_id, entry_id, kind=_INSURANCE
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Log entry not found")
