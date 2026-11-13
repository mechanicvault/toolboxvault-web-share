"""Claims HTTP surface — WARRANTY / REPAIR claims only (claims
separation, 2026-11-05). Thin: parse, gate, call the service, map
errors. All business rules live in service.py.

Disaster (insurance) claims live in the disaster_claims module
under /api/disaster-claims — every route here resolves claims
through the WARRANTY kind scope, so an insurance claim addressed
here is a 404, exactly like a stranger's claim.

Gated by the module-control system (mechanic + shop by default):
a user whose groups don't include claims gets
403 {code: module_unavailable} here, and the home "Open claims"
stat rides the same gate via /api/core/my-modules.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, require_module
from app.modules.claims import models as claim_models
from app.modules.claims import schemas, service

router = APIRouter(tags=["claims"])

_claims_module = require_module("claims")
_dealers_module = require_module("dealers")

_WARRANTY = claim_models.KIND_WARRANTY


def _as_http(exc: service.ClaimsError) -> HTTPException:
    if isinstance(exc, service.ClaimsNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _party_view(db: Session, user, claim_id: uuid.UUID):
    """Resolve a claim for a TWO-PARTY route and apply the module
    gate for the caller's seat (two-types build): the claim's
    owner rides the CLAIMS module; a dealer the claim is
    addressed to rides the DEALERS module — a dealer-only account
    holds no claims entitlement, and the plain claims gate would
    lock them out of work addressed to them. Returns
    (claim, owner, role). A non-party gets a 404 — or the claims
    403 when they don't even hold the module, which is the gate's
    standing answer for any claim id."""
    from app.modules.core import module_control

    try:
        claim, owner, role = service.get_claim_for_viewer(
            db, user, claim_id, kind=_WARRANTY
        )
    except service.ClaimsNotFound:
        if not module_control.effective_for_user(
            db, "claims", user.account_types, user_id=user.id, tier=user.tier, beta_tester=user.beta_tester
        ):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "module_unavailable",
                    "module": "claims",
                    "message": "This module isn't enabled for your account.",
                },
            )
        raise HTTPException(status_code=404, detail="That claim doesn't exist.")
    module_id = "claims" if role == "owner" else "dealers"
    if not module_control.effective_for_user(
        db, module_id, user.account_types, user_id=user.id, tier=user.tier, beta_tester=user.beta_tester
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "module_unavailable",
                "module": module_id,
                "message": "This module isn't enabled for your account.",
            },
        )
    return claim, owner, role


@router.get("/stats", response_model=schemas.ClaimsStats)
def claims_stats(
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    return service.stats(db, user.id, _WARRANTY)


@router.get("/targets", response_model=schemas.TargetsView)
def claim_targets(
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    """The wizard's picker: the owner's assets with the values a
    line can price from and the attachments evidence can use."""
    return service.list_targets(db, user)


@router.get("/incoming", response_model=list[schemas.IncomingClaimSummary])
def incoming_claims(
    user: CurrentUser = Depends(_dealers_module),
    db: Session = Depends(get_db),
):
    """The AGENT side's worklist: warranty claims currently
    routed to this user as the assigned agent (2026-10-31).
    Gated by the DEALERS module (the surface lives on the dealer
    dashboard), not by claims — a dealer-only account holds no
    claims entitlement of its own."""
    return service.list_incoming_claims(db, user)


@router.get(
    "/warranty/agent-options", response_model=schemas.WarrantyFilingOptions
)
def warranty_agent_options(
    target_kind: str,
    target_id: uuid.UUID,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    """The broken-item form's agent step for one target: the
    dealer the claim will name + the owner's agents on record
    for it (the pick list and which one is the default)."""
    try:
        return service.warranty_filing_options(
            db, user, target_kind=target_kind, target_id=target_id
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)


@router.post(
    "/warranty", response_model=schemas.WarrantyCreateResult, status_code=201
)
def create_warranty_claim(
    payload: schemas.WarrantyClaimCreate,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    """The broken-item flow's claim: auto-created for the item
    (or one set piece), routed to the owner's agent for the
    item's dealer (the agent on record unless the payload names
    another recorded agent, or none) and auto-reported to that
    agent when a channel reaches them. The result says whether
    the agent was reached, and how."""
    try:
        claim, report = service.create_warranty_claim(
            db,
            user,
            target_kind=payload.target_kind,
            target_id=payload.target_id,
            include_addons=payload.include_addons,
            dealer_notified=payload.dealer_notified,
            problem=payload.problem,
            agent_user_id=payload.agent_user_id,
            private_agent_id=payload.private_agent_id,
            no_agent=payload.no_agent,
            filed_with=payload.filed_with,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return {
        "claim": service.claim_view(db, user, claim),
        "reported": report["reported"],
        "report_via": report["via"],
    }


@router.post("/replace-item", response_model=schemas.ReplaceItemResult)
def replace_item(
    payload: schemas.ReplaceItemRequest,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    """The broken prompt's Replace: "same" creates the new item
    with the old one's data (new price + date) and retires the
    old one; "different" just retires it for the add flow."""
    try:
        return service.replace_item(
            db,
            user,
            item_kind=payload.item_kind,
            item_id=payload.item_id,
            mode=payload.mode,
            amount_spent=payload.amount_spent,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)


@router.get("", response_model=list[schemas.ClaimSummary])
def list_claims(
    include_archived: bool = False,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    claims = service.list_claims(
        db, user, include_archived=include_archived, kind=_WARRANTY
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


@router.get(
    "/for-item/{kind}/{item_id}", response_model=schemas.ItemClaimsView
)
def claims_for_item(
    kind: str,
    item_id: uuid.UUID,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    """The item page's corner of the dealer triangle: this item's
    claims, current + history. `kind` is the item-page kind
    (tool | battery); a set is a tool here, as everywhere."""
    if kind not in ("tool", "battery"):
        raise HTTPException(status_code=404, detail="That item doesn't exist.")
    try:
        return service.claims_for_item(db, user, kind, item_id)
    except service.ClaimsError as exc:
        raise _as_http(exc)


@router.get("/{claim_id}", response_model=schemas.ClaimView)
def get_claim(
    claim_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One claim, from either seat: the owner, or — for a
    warranty claim — the claim's assigned agent (their view
    carries viewer_role="dealer" and only the agent moves)."""
    claim, owner, role = _party_view(db, user, claim_id)
    return service.claim_view(db, owner, claim, viewer_role=role)


@router.patch("/{claim_id}", response_model=schemas.ClaimView)
def update_claim(
    claim_id: uuid.UUID,
    payload: schemas.ClaimUpdate,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    try:
        claim = service.update_claim(
            db,
            user,
            claim_id,
            kind=_WARRANTY,
            **payload.model_dump(exclude_unset=True),
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, user, claim)


@router.patch("/{claim_id}/agent", response_model=schemas.ClaimView)
def set_claim_agent(
    claim_id: uuid.UUID,
    payload: schemas.ClaimAgentUpdate,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    """Re-point a warranty claim at a different agent of record
    for its dealer — or at no agent (both ids null). The owner's
    hand on the routing (2026-10-31); it holds until the next
    agent-on-record change sweeps the dealer's claims."""
    try:
        claim = service.set_claim_agent(
            db,
            user,
            claim_id,
            agent_user_id=payload.agent_user_id,
            private_agent_id=payload.private_agent_id,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, user, claim)


@router.delete("/{claim_id}", status_code=204)
def delete_claim(
    claim_id: uuid.UUID,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    try:
        deleted = service.delete_claim(db, user, claim_id, kind=_WARRANTY)
    except service.ClaimsError as exc:
        raise _as_http(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Claim not found")


@router.post("/{claim_id}/transition", response_model=schemas.ClaimView)
def transition_claim(
    claim_id: uuid.UUID,
    payload: schemas.TransitionRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _claim, owner, role = _party_view(db, user, claim_id)
    try:
        claim = service.transition(
            db,
            user,
            claim_id,
            payload.to_status,
            repair_sent_to=payload.repair_sent_to,
            repair_cost=payload.repair_cost,
            kind=_WARRANTY,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, owner, claim, viewer_role=role)


@router.post("/{claim_id}/archive", response_model=schemas.ClaimView)
def archive_claim(
    claim_id: uuid.UUID,
    payload: schemas.ArchiveRequest,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    try:
        claim = service.set_archived(
            db, user, claim_id, payload.archived, kind=_WARRANTY
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.claim_view(db, user, claim)


# -- evidence ---------------------------------------------------------------------


@router.post(
    "/{claim_id}/evidence", response_model=schemas.EvidenceView, status_code=201
)
def add_evidence_reference(
    claim_id: uuid.UUID,
    payload: schemas.EvidenceReferenceCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _party_view(db, user, claim_id)
    try:
        row = service.add_evidence_reference(
            db,
            user,
            claim_id,
            item_kind=payload.item_kind,
            item_id=payload.item_id,
            attachment_key=payload.attachment_key,
            kind=_WARRANTY,
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _party_view(db, user, claim_id)
    try:
        return service.issue_evidence_upload_url(
            db,
            user,
            claim_id,
            kind=payload.kind,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            claim_kind=_WARRANTY,
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _party_view(db, user, claim_id)
    try:
        row = service.attach_evidence_upload(
            db,
            user,
            claim_id,
            key=payload.key,
            filename=payload.filename,
            kind=_WARRANTY,
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.evidence_view(db, row.owner_id, row)


@router.delete("/{claim_id}/evidence/{evidence_id}", status_code=204)
def remove_evidence(
    claim_id: uuid.UUID,
    evidence_id: uuid.UUID,
    user: CurrentUser = Depends(_claims_module),
    db: Session = Depends(get_db),
):
    try:
        removed = service.remove_evidence(
            db, user, claim_id, evidence_id, kind=_WARRANTY
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _party_view(db, user, claim_id)
    try:
        row = service.add_communication(
            db,
            user,
            claim_id,
            channel=payload.channel,
            contact=payload.contact,
            summary=payload.summary,
            occurred_at=payload.occurred_at,
            kind=_WARRANTY,
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _party_view(db, user, claim_id)
    try:
        row = service.update_communication(
            db,
            user,
            claim_id,
            entry_id,
            kind=_WARRANTY,
            **payload.model_dump(exclude_unset=True),
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    return service.comm_view(row)


@router.delete("/{claim_id}/communications/{entry_id}", status_code=204)
def delete_communication(
    claim_id: uuid.UUID,
    entry_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _party_view(db, user, claim_id)
    try:
        deleted = service.delete_communication(
            db, user, claim_id, entry_id, kind=_WARRANTY
        )
    except service.ClaimsError as exc:
        raise _as_http(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Log entry not found")
