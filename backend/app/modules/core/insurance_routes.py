"""My Insurance profile routes (Package C): the caller's own
insurer + agent record (Settings → My Insurance). Plain auth — the
profile is core account data, available to every account group;
the claims flow consumes it server-side through insurance.py.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.core import insurance, schemas

router = APIRouter(tags=["insurance"])


@router.get("/insurance", response_model=schemas.InsuranceProfileView)
def get_insurance_profile(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return insurance.profile_view(insurance.get_profile(db, user.id), db)


@router.put("/insurance", response_model=schemas.InsuranceProfileView)
def put_insurance_profile(
    payload: schemas.InsuranceProfileUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        profile = insurance.upsert_profile(db, user, **payload.model_dump())
    except ValueError as exc:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    return insurance.profile_view(profile, db)
