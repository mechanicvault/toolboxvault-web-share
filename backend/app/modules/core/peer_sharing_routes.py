"""Peer-sharing routes (core module), mounted on the core router.

HTTP layer only — logic lives in peer_sharing.py. Grants are acted on
through the caller's own relationship to them (owner for revoke,
addressed viewer for accept/decline/leave); an id that isn't the
caller's to touch is a 404, indistinguishable from nonexistent.

Route-order note: these are registered before sharing_routes' group
routes in routes.py — "/sharing/peer/..." would otherwise be
swallowed by "/sharing/{group}"-style patterns.

Module gating (module doctrine, owner 2026-10-18): peer sharing is
the shared_tools FEATURE module. Its data surfaces — overview,
per-person lists, search, sending invites, holding exclusions — are
gated with require_module("shared_tools"), whose seeded assignment
(mechanic + shop) reproduces the old require_account_type owner
gate. The four grant-lifecycle endpoints (accept / decline /
revoke / leave) stay behind plain authentication on purpose: they
expose no tool data, and no one may ever be trapped in a grant
because a switch moved — either side can always end the
relationship, and an invitee in any group can always answer.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, require_module
from app.modules.core import peer_sharing, schemas
from app.modules.core import service as core_service

router = APIRouter()

_peer_module = require_module("shared_tools")


def _as_http(exc: peer_sharing.PeerSharingError) -> HTTPException:
    if isinstance(exc, peer_sharing.PeerNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _account(user: CurrentUser, db: Session):
    account = core_service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    return account


@router.post(
    "/sharing/peer/invite",
    response_model=schemas.PeerOutgoingGrant,
    status_code=status.HTTP_201_CREATED,
)
def invite_peer(
    payload: schemas.PeerInviteRequest,
    user: CurrentUser = Depends(_peer_module),
    db: Session = Depends(get_db),
):
    """Invite one person (by account number or email) to see my
    list. Idempotent — an existing grant is returned as-is. Email
    invites answer identically whether or not the address has an
    account."""
    try:
        return peer_sharing.invite(
            db,
            _account(user, db),
            account_number=payload.account_number,
            email=str(payload.email) if payload.email is not None else None,
        )
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)


@router.get("/sharing/peer", response_model=schemas.PeerOverview)
def get_peer_overview(
    user: CurrentUser = Depends(_peer_module),
    db: Session = Depends(get_db),
):
    """My peer-sharing world: grants I've made, accepted grants to
    me, invites awaiting my decision, my exclusions, my tools."""
    return peer_sharing.get_overview(db, _account(user, db))


@router.post("/sharing/peer/{grant_id}/accept", status_code=204)
def accept_peer(
    grant_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        peer_sharing.accept(db, _account(user, db), grant_id)
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)


@router.post("/sharing/peer/{grant_id}/decline", status_code=204)
def decline_peer(
    grant_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        peer_sharing.decline(db, _account(user, db), grant_id)
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)


@router.post("/sharing/peer/{grant_id}/revoke", status_code=204)
def revoke_peer(
    grant_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        peer_sharing.revoke(db, _account(user, db), grant_id)
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)


@router.post("/sharing/peer/{grant_id}/leave", status_code=204)
def leave_peer(
    grant_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        peer_sharing.leave(db, _account(user, db), grant_id)
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)


@router.put(
    "/sharing/peer/exclusions", response_model=schemas.PeerExclusionsResponse
)
def put_peer_exclusions(
    payload: schemas.PeerExclusionsUpdate,
    user: CurrentUser = Depends(_peer_module),
    db: Session = Depends(get_db),
):
    """Replace the set of items I withhold from ALL peer viewers."""
    try:
        excluded_tools, excluded_batteries = peer_sharing.set_exclusions(
            db,
            _account(user, db),
            list(payload.tool_ids),
            battery_ids=list(payload.battery_ids),
        )
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)
    return {
        "excluded_tool_ids": excluded_tools,
        "excluded_battery_ids": excluded_batteries,
    }


@router.put("/sharing/peer/set-choices", response_model=schemas.PeerSetChoiceView)
def put_peer_set_choice(
    payload: schemas.PeerSetChoiceUpdate,
    user: CurrentUser = Depends(_peer_module),
    db: Session = Depends(get_db),
):
    """Store my "include addon pieces?" choice for one of my sets on
    the peer list (attached tools + addon pieces ride inside the set
    entry or stay home, per the choice; core pieces always ride)."""
    account = _account(user, db)
    try:
        include = peer_sharing.set_peer_set_choice(
            db, account, payload.tool_id, payload.include_addons
        )
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)
    return {
        "tool_id": payload.tool_id,
        "name": "",
        "include_addons": include,
    }


@router.post(
    "/sharing/peer/exclusion-rules",
    response_model=schemas.PeerExclusionRuleView,
    status_code=status.HTTP_201_CREATED,
)
def post_peer_exclusion_rule(
    payload: schemas.PeerExclusionRuleCreate,
    user: CurrentUser = Depends(_peer_module),
    db: Session = Depends(get_db),
):
    """Add a scope withholding rule (Package C): everything in a
    category, a location subtree, or under a tag stops reaching
    every peer viewer — including items filed there later."""
    try:
        return peer_sharing.create_exclusion_rule(
            db,
            _account(user, db),
            scope=payload.scope,
            scope_value=payload.scope_value,
            scope_ref_id=payload.scope_ref_id,
        )
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)


@router.delete(
    "/sharing/peer/exclusion-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_peer_exclusion_rule(
    rule_id: uuid.UUID,
    user: CurrentUser = Depends(_peer_module),
    db: Session = Depends(get_db),
):
    try:
        peer_sharing.delete_exclusion_rule(db, _account(user, db), rule_id)
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)


@router.get("/sharing/peer/lists/{owner_id}")
def get_peer_list(
    owner_id: uuid.UUID,
    user: CurrentUser = Depends(_peer_module),
    db: Session = Depends(get_db),
):
    """One owner's list, exactly as I may see it (accepted grant
    required). No response_model on purpose — the payload's keys ARE
    the privacy decision (the fixed whitelist from inventory's
    peer_tool_view plus owner attribution), so the dicts go out
    untouched."""
    try:
        return peer_sharing.list_for_viewer(db, _account(user, db), owner_id)
    except peer_sharing.PeerSharingError as exc:
        raise _as_http(exc)


@router.get("/sharing/peer/search")
def search_peer(
    q: Annotated[str, Query()] = "",
    user: CurrentUser = Depends(_peer_module),
    db: Session = Depends(get_db),
):
    """Search across everyone who shares with me. An empty q returns
    nothing — searching is deliberate; browsing is per-person."""
    return peer_sharing.search_for_viewer(db, _account(user, db), q)
