"""Consent-sharing routes (core module), mounted on the core router.

HTTP layer only — logic lives in sharing.py. Every route resolves
the caller and operates on THEIR sharing setup; there is no path
parameter that could name another owner, so cross-owner access is
impossible by construction.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.core import module_control, schemas, sharing

router = APIRouter()


def _require_inventory_reach(user: CurrentUser, db: Session) -> None:
    """Settings follow reach (owner ruling, 2026-11-09): every
    WRITE below configures the sharing of the caller's INVENTORY
    — what a user shares IS their tools — so an account that
    cannot reach the inventory module cannot change these
    settings, exactly as it cannot change its inventory's custom
    fields (the inventory router's own gate). Reads stay open:
    losing reach never hides what a user already set up, it only
    stops the changes. The refusal wears the module gate's own
    shape ({code: module_unavailable}), like every other door."""
    if not module_control.effective_for_user(
        db,
        "inventory",
        user.account_types,
        user_id=user.id,
        tier=user.tier,
        beta_tester=user.beta_tester,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "module_unavailable",
                "module": "inventory",
                "message": "This module isn't enabled for your account.",
            },
        )

# Path/query values are closed Literals from schemas — anything that
# is not shop_company|insurance fails validation with a 422 before a
# handler runs.
GroupPath = Annotated[schemas.ShareRecipientGroup, Path()]
GroupQuery = Annotated[schemas.ShareRecipientGroup, Query()]


def _as_422(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


@router.get("/sharing", response_model=schemas.SharingOverview)
def get_sharing(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's sharing setup: both groups' configs + their tools
    with per-group shared flags (Settings → Sharing renders this)."""
    return sharing.get_overview(db, user.id)


@router.get("/sharing/preview")
def get_sharing_preview(
    response: Response,
    group: GroupQuery,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exactly what a connected recipient in `group` receives: the
    caller's shared items with only the shared fields present.

    No response_model on purpose — the payload's keys ARE the consent
    decision (unchosen fields are absent, not nulled), so the dicts
    from the service go out untouched.

    Paged (step-4 fix D4): `limit`/`offset` page the response and
    the full resolved count rides X-Total-Count; without `limit`
    the whole set returns, exactly as before."""
    page, total = sharing.build_preview_page(
        db, user.id, group, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return page


@router.put("/sharing/{group}", response_model=schemas.ShareGroupState)
def put_share_config(
    group: GroupPath,
    payload: schemas.ShareConfigUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_inventory_reach(user, db)
    try:
        return sharing.update_config(
            db, user.id, group, payload.enabled, list(payload.fields)
        )
    except sharing.SharingError as exc:
        raise _as_422(exc)


@router.put("/sharing/{group}/items", response_model=schemas.ShareGroupState)
def put_shared_items(
    group: GroupPath,
    payload: schemas.ShareItemsUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_inventory_reach(user, db)
    try:
        return sharing.set_shared_items(
            db,
            user.id,
            group,
            list(payload.tool_ids),
            battery_ids=list(payload.battery_ids),
            set_choices=[choice.model_dump() for choice in payload.set_choices],
        )
    except sharing.SharingError as exc:
        raise _as_422(exc)


@router.get("/sharing/summary")
def get_sharing_summary(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The at-a-glance picture for the Shared Tools page (Package
    C): tier sharing on/off + live resolved counts per group, and
    peer grant counts. Read-only — no response model, the service
    dict goes out as built."""
    return sharing.sharing_summary(db, user)


@router.post(
    "/sharing/{group}/rules",
    response_model=schemas.ShareGroupState,
    status_code=status.HTTP_201_CREATED,
)
def post_share_rule(
    group: GroupPath,
    payload: schemas.ShareRuleCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a scope rule to the group (Package C). Rules resolve
    dynamically: items matching the scope are shared from this
    moment on — including items that don't exist yet."""
    _require_inventory_reach(user, db)
    try:
        return sharing.create_rule(db, user.id, group, **payload.model_dump())
    except sharing.SharingError as exc:
        raise _as_422(exc)


@router.put(
    "/sharing/{group}/rules/{rule_id}", response_model=schemas.ShareGroupState
)
def put_share_rule(
    group: GroupPath,
    rule_id: uuid.UUID,
    payload: schemas.ShareRuleUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_inventory_reach(user, db)
    try:
        return sharing.update_rule(
            db,
            user.id,
            group,
            rule_id,
            include_addons=payload.include_addons,
            scope_value=payload.scope_value,
        )
    except sharing.SharingError as exc:
        raise _as_422(exc)


@router.delete(
    "/sharing/{group}/rules/{rule_id}", response_model=schemas.ShareGroupState
)
def delete_share_rule(
    group: GroupPath,
    rule_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_inventory_reach(user, db)
    try:
        return sharing.delete_rule(db, user.id, group, rule_id)
    except sharing.SharingError as exc:
        raise _as_422(exc)


@router.put("/sharing/{group}/exclusions", response_model=schemas.ShareGroupState)
def put_share_exclusions(
    group: GroupPath,
    payload: schemas.ShareExclusionsUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace the group's per-item exclusions (Package C): items
    withheld even when a rule or a pick would share them."""
    _require_inventory_reach(user, db)
    try:
        return sharing.set_exclusions(
            db, user.id, group, list(payload.tool_ids), list(payload.battery_ids)
        )
    except sharing.SharingError as exc:
        raise _as_422(exc)
