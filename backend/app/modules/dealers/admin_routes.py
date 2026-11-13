"""Operator surface for the dealer DIRECTORY (Admin -> Dealer
directory). Directory rows are platform data: operators curate them;
regular users only ever create PRIVATE companies through the module
routes. Every mutation writes an audit row, like every other admin
surface.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_operator
from app.modules.core import audit
from app.modules.dealers import models, portal, schemas, service

router = APIRouter()


@router.get("/dealer-companies", response_model=list[schemas.CompanyView])
def list_directory(
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.DealerCompany)
        .filter(models.DealerCompany.is_directory.is_(True))
        .order_by(models.DealerCompany.name.asc())
        .all()
    )
    return [service.serialize_company(c) for c in rows]


@router.post(
    "/dealer-companies",
    response_model=schemas.CompanyView,
    status_code=status.HTTP_201_CREATED,
)
def create_directory_company(
    payload: schemas.CompanyWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        company = service.create_company(db, owner_id=None, data=payload.model_dump())
    except service.DealerError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    audit.record(
        db,
        actor=operator,
        action="dealer_company.create",
        target=f"dealer_company:{company.id}",
        detail={"name": company.name},
    )
    return service.serialize_company(company)


@router.put("/dealer-companies/{company_id}", response_model=schemas.CompanyView)
def update_directory_company(
    company_id: uuid.UUID,
    payload: schemas.CompanyWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    company = service.get_directory_company(db, company_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Directory company not found."
        )
    try:
        company = service.update_company(db, company, payload.model_dump())
    except service.DealerError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    audit.record(
        db,
        actor=operator,
        action="dealer_company.update",
        target=f"dealer_company:{company.id}",
        detail={"name": company.name},
    )
    return service.serialize_company(company)


@router.delete(
    "/dealer-companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_directory_company(
    company_id: uuid.UUID,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    company = service.get_directory_company(db, company_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Directory company not found."
        )
    audit.record(
        db,
        actor=operator,
        action="dealer_company.delete",
        target=f"dealer_company:{company.id}",
        detail={"name": company.name},
    )
    service.delete_company(db, company)


# ---------------------------------------------------------------------
# Representations review (dealer portal): agents self-assert the
# companies they run trucks for; an operator verifies the claim.
# ---------------------------------------------------------------------


@router.get(
    "/dealer-representations",
    response_model=list[schemas.RepresentationAdminView],
)
def list_representations(
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return [
        portal.serialize_representation_admin(db, row)
        for row in portal.list_representations_admin(db)
    ]


@router.put(
    "/dealer-representations/{rep_id}/verify",
    response_model=schemas.RepresentationAdminView,
)
def set_representation_verified(
    rep_id: uuid.UUID,
    payload: schemas.RepresentationVerify,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    row = portal.set_representation_verified(
        db, rep_id, payload.verified, operator.id
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Representation not found.",
        )
    view = portal.serialize_representation_admin(db, row)
    audit.record(
        db,
        actor=operator,
        action=(
            "dealer_representation.verify"
            if payload.verified
            else "dealer_representation.unverify"
        ),
        target=f"dealer_representation:{row.id}",
        detail={
            "agent": view["agent_account_number"],
            "company": view["company_name"],
        },
    )
    return view
