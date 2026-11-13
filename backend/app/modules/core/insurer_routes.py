"""Insurer routes (wave 3): the public directory read, the
insurance-group user's own Insurer Profile (affiliation), and
the verified Policyholders surface.

Directory READS are plain auth (every user picks from it in My
Insurance). Affiliation writes require the insurance group (the
service refuses). The Policyholders surface exists only for
VERIFIED affiliations — unverified callers get a 422 with the
reason, and a policyholder who fails either gate (picked this
company + sharing on) reads as not-found.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.core import insurers, schemas, service

router = APIRouter(tags=["insurers"])


def _as_http(exc: insurers.InsurerError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if isinstance(exc, insurers.InsurerNotFound)
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return HTTPException(status_code=code, detail=str(exc))


def _account(db: Session, user: CurrentUser):
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists"
        )
    return account


@router.get("/insurers/directory", response_model=list[schemas.InsurerCompanyView])
def directory(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [insurers.company_view(c) for c in insurers.list_companies(db)]


@router.get(
    "/insurers/affiliation",
    response_model=schemas.InsurerAffiliationView | None,
)
def my_affiliation(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = insurers.my_affiliation(db, user.id)
    return insurers.affiliation_view(db, row) if row else None


@router.put(
    "/insurers/affiliation", response_model=schemas.InsurerAffiliationView
)
def set_affiliation(
    payload: schemas.InsurerAffiliationWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = insurers.set_affiliation(
            db, _account(db, user), payload.company_id, payload.role_at_company
        )
    except insurers.InsurerError as exc:
        raise _as_http(exc)
    return insurers.affiliation_view(db, row)


@router.delete("/insurers/affiliation", status_code=status.HTTP_204_NO_CONTENT)
def clear_affiliation(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    insurers.clear_affiliation(db, _account(db, user))


@router.get("/insurers/policyholders", response_model=list[schemas.PolicyholderView])
def policyholders(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return insurers.list_policyholders(db, _account(db, user))
    except insurers.InsurerError as exc:
        raise _as_http(exc)


@router.get("/insurers/policyholders/{policyholder_id}/preview")
def policyholder_preview(
    policyholder_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The policyholder's shared inventory, exactly as the
    existing tier-sharing preview renders it (same payload the
    owner's own Sharing settings preview shows)."""
    try:
        return insurers.policyholder_preview(
            db, _account(db, user), policyholder_id
        )
    except insurers.InsurerError as exc:
        raise _as_http(exc)
