"""Shop crew routes (wave 3): the owner's "My crew" surface and
the employee's invite inbox + "My shop" surface.

Owner routes gate on the shop_company group (the service refuses
with a friendly 422); employee routes are plain auth — anyone can
be invited into a crew. Plain auth throughout: crew is account
structure (like tier sharing), not a gated feature module.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.core import crew, schemas, service

router = APIRouter(tags=["crew"])


def _as_http(exc: crew.CrewError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if isinstance(exc, crew.CrewNotFound)
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


# -- owner surface ---------------------------------------------------------------


@router.get("/crew", response_model=list[schemas.CrewMembershipView])
def my_roster(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        rows = crew.roster(db, _account(db, user))
    except crew.CrewError as exc:
        raise _as_http(exc)
    return [crew.membership_view(db, r) for r in rows]


@router.get("/crew/summary", response_model=schemas.CrewSummaryView)
def my_crew_summary(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return crew.crew_summary(db, _account(db, user))
    except crew.CrewError as exc:
        raise _as_http(exc)


@router.post(
    "/crew/invite",
    response_model=schemas.CrewMembershipView,
    status_code=status.HTTP_201_CREATED,
)
def invite(
    payload: schemas.CrewInviteWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if bool(payload.email) == bool(payload.account_number):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invite by email OR by account number — not both.",
        )
    try:
        if payload.email:
            row = crew.invite_by_email(
                db, _account(db, user), payload.email, payload.role_label
            )
        else:
            row = crew.invite_by_account_number(
                db,
                _account(db, user),
                payload.account_number or "",
                payload.role_label,
            )
    except crew.CrewError as exc:
        raise _as_http(exc)
    return crew.membership_view(db, row)


@router.get(
    "/crew/members/{member_user_id}/tools",
    response_model=schemas.CrewMemberToolsView,
)
def member_tools(
    member_user_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The shop's read-only view of one active crew member's
    shared tool list (claims-ownership lane, 2026-11-07). No
    write of any kind rides this surface."""
    try:
        return crew.member_tools(db, _account(db, user), member_user_id)
    except crew.CrewError as exc:
        raise _as_http(exc)


@router.post(
    "/crew/{membership_id}/remove",
    response_model=schemas.CrewMembershipView,
)
def remove(
    membership_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = crew.remove_member(db, _account(db, user), membership_id)
    except crew.CrewError as exc:
        raise _as_http(exc)
    return crew.membership_view(db, row)


# -- employee surface --------------------------------------------------------------


@router.get("/crew/invites", response_model=list[schemas.CrewMembershipView])
def my_invites(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = crew.my_invites(db, _account(db, user))
    return [crew.membership_view(db, r) for r in rows]


@router.get("/crew/my-shops", response_model=list[schemas.CrewMembershipView])
def my_shops(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = crew.my_shops(db, _account(db, user))
    return [crew.membership_view(db, r) for r in rows]


@router.post(
    "/crew/invites/{membership_id}/respond",
    response_model=schemas.CrewMembershipView,
)
def respond(
    membership_id: uuid.UUID,
    payload: schemas.CrewRespondWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = crew.respond(db, _account(db, user), membership_id, payload.accept)
    except crew.CrewError as exc:
        raise _as_http(exc)
    return crew.membership_view(db, row)


@router.post(
    "/crew/my-shops/{membership_id}/leave",
    response_model=schemas.CrewMembershipView,
)
def leave(
    membership_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = crew.leave_shop(db, _account(db, user), membership_id)
    except crew.CrewError as exc:
        raise _as_http(exc)
    return crew.membership_view(db, row)
