"""Operator surface for the insurer DIRECTORY (Admin → Insurer
directory, wave 3). Mirrors the dealer directory's admin routes:
directory rows are platform data, operators curate them, and
every mutation writes an audit row. Affiliation verification
lives here too — the operator confirms an insurance-group user
really represents the company they picked.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_operator
from app.modules.core import audit, insurers, schemas

router = APIRouter()


@router.get("/insurer-companies", response_model=list[schemas.InsurerCompanyView])
def list_directory(
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return [insurers.company_view(c) for c in insurers.list_companies(db)]


@router.post(
    "/insurer-companies",
    response_model=schemas.InsurerCompanyView,
    status_code=status.HTTP_201_CREATED,
)
def create_company(
    payload: schemas.InsurerCompanyWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        company = insurers.create_company(db, payload.model_dump())
    except insurers.InsurerError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    audit.record(
        db,
        actor=operator,
        action="insurer_company.create",
        target=f"insurer_company:{company.id}",
        detail={"name": company.name},
    )
    return insurers.company_view(company)


@router.put("/insurer-companies/{company_id}", response_model=schemas.InsurerCompanyView)
def update_company(
    company_id: uuid.UUID,
    payload: schemas.InsurerCompanyWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    company = insurers.get_company(db, company_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Directory company not found."
        )
    try:
        company = insurers.update_company(db, company, payload.model_dump())
    except insurers.InsurerError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    audit.record(
        db,
        actor=operator,
        action="insurer_company.update",
        target=f"insurer_company:{company.id}",
        detail={"name": company.name},
    )
    return insurers.company_view(company)


@router.delete(
    "/insurer-companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_company(
    company_id: uuid.UUID,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    company = insurers.get_company(db, company_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Directory company not found."
        )
    insurers.delete_company(db, company)
    audit.record(
        db,
        actor=operator,
        action="insurer_company.delete",
        target=f"insurer_company:{company_id}",
        detail={"name": company.name},
    )


@router.get(
    "/insurer-affiliations",
    response_model=list[schemas.InsurerAffiliationAdminView],
)
def list_affiliations(
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return [
        insurers.affiliation_admin_view(db, row)
        for row in insurers.list_affiliations_admin(db)
    ]


@router.put(
    "/insurer-affiliations/{affiliation_id}/verified",
    response_model=schemas.InsurerAffiliationAdminView,
)
def set_verified(
    affiliation_id: uuid.UUID,
    payload: schemas.InsurerVerifyWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    row = insurers.set_affiliation_verified(
        db, affiliation_id, payload.verified, operator.id
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Affiliation not found."
        )
    audit.record(
        db,
        actor=operator,
        action=(
            "insurer_affiliation.verify"
            if payload.verified
            else "insurer_affiliation.unverify"
        ),
        target=f"insurer_affiliation:{row.id}",
        detail={"user_id": str(row.user_id), "company_id": str(row.company_id)},
    )
    return insurers.affiliation_admin_view(db, row)
