"""Onboarding wizard routes (owner design 2026-10-31, built
2026-11-07): the setup plan and its progress writes.

The plan is computed per read from the live registries (module
control) and the account itself (the probe steps) — see
app/modules/core/onboarding.py for the model. The wizard's steps
write through the ordinary settings machinery (account-type, /me,
module switches, settings sections); these four routes only carry
where the account stands in the pass.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.core import onboarding, schemas, service

router = APIRouter()


def _account(user: CurrentUser, db: Session):
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    return account


@router.get("/onboarding", response_model=schemas.OnboardingPlanView)
def get_onboarding(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's setup plan. Reading it also takes baselines
    and mints new-feature notifications (each exactly once) —
    the living part of the design breathes on this read."""
    return onboarding.get_plan(db, _account(user, db))


@router.post("/onboarding/progress", response_model=schemas.OnboardingPlanView)
def post_onboarding_progress(
    payload: schemas.OnboardingProgressRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record one step done or skipped; returns the fresh plan."""
    try:
        return onboarding.set_progress(
            db, _account(user, db), payload.step_key, payload.status
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/onboarding/dismiss", response_model=schemas.OnboardingPlanView)
def post_onboarding_dismiss(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Waive setup prompts (the banner stands down; setup itself
    stays open and unfinished steps keep their state)."""
    return onboarding.dismiss(db, _account(user, db))


@router.post("/onboarding/reopen", response_model=schemas.OnboardingPlanView)
def post_onboarding_reopen(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Undo a waiver — the banner may speak again."""
    return onboarding.reopen(db, _account(user, db))
