"""Module-control routes (module doctrine, owner 2026-10-18).

Two surfaces over app/modules/core/module_control.py:

- `router` (mounted on the core router): GET /my-modules — the
  caller's effective feature modules, driving the frontend nav,
  home tiles, and stat visibility; GET /my-module-prefs + PUT
  /my-modules/{id} — the caller's OWN module switches (per-user
  layer, owner 2026-10-24); GET /module-options — the public
  signup preview of what a group set entitles.
- `admin_router` (mounted by main.py at /api/admin): the operator
  matrix and the two switch PUTs. Operator-only, every route.

Changes apply on the very next request: the service reads the
stored switches per request, nothing is cached.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, require_operator
from app.modules.core import (
    audit,
    module_control,
    module_release,
    nav_badges,
    schemas,
    tiers,
)
from app.modules.core.account_types import ACCOUNT_TYPES

router = APIRouter()
admin_router = APIRouter()


@router.get("/my-modules", response_model=list[schemas.EffectiveModule])
def my_modules(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The feature modules effective for the caller right now —
    operator layer AND the caller's own switches."""
    return module_control.effective_modules(
        db,
        user.account_types,
        user_id=user.id,
        tier=user.tier,
        beta_tester=user.beta_tester,
    )


@router.get("/nav-badges", response_model=dict[str, str])
def nav_badge_registry(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The NEW-badge registry (release machinery, 2026-11-08):
    nav item key -> release date ("YYYY-MM-DD"), read from the
    system-settings store (nav_badges.py). The shell fetches it
    once per session and computes each badge's first-week
    freshness at render — the server serves the map verbatim
    and never decides what is still new."""
    return nav_badges.get_nav_badges(db)


@router.get("/my-module-prefs", response_model=list[schemas.ModulePref])
def my_module_prefs(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Every feature module the caller's groups entitle, with the
    caller's own switch state — the Settings → Site settings
    Modules list."""
    return module_control.user_module_prefs(db, user)


@router.put("/my-modules/{module_id}", response_model=schemas.ModulePref)
def set_my_module(
    module_id: str,
    payload: schemas.ModuleToggleRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Flip the caller's own switch for one module. Takes effect
    on the very next request, everywhere, like the operator's."""
    try:
        return module_control.set_user_module_pref(
            db, user, module_id, payload.enabled
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown module."
        )
    except ValueError as exc:
        if str(exc) == "module_always_on":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "module_always_on",
                    "module": module_id,
                    "message": "This module is always on.",
                },
            )
        raise
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "module_unavailable",
                "module": module_id,
                "message": "This module isn't enabled for your account.",
            },
        )


@router.get("/module-options", response_model=list[schemas.ModuleOption])
def module_options(
    groups: str = Query(...),
    db: Session = Depends(get_db),
):
    """PUBLIC (no auth): the modules a group set entitles — the
    signup flow's module-selection preview, which must render
    before an account exists. `groups` is a comma-separated list
    of account groups; an empty or unknown group is a 422."""
    parsed: list[str] = []
    for part in groups.split(","):
        group = part.strip()
        if group and group not in parsed:
            parsed.append(group)
    if not parsed or any(g not in ACCOUNT_TYPES for g in parsed):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="groups must name at least one known account group.",
        )
    return module_control.module_options(db, parsed)


@admin_router.get("/modules", response_model=list[schemas.AdminModule])
def admin_list_modules(
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """The full control matrix: manifests, switches, health."""
    return module_control.admin_matrix(db)


@admin_router.put(
    "/modules/{module_id}/global", response_model=schemas.AdminModule
)
def admin_set_global(
    module_id: str,
    payload: schemas.ModuleToggleRequest,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Flip a module's global switch (the kill switch)."""
    try:
        result = module_control.set_global_enabled(db, module_id, payload.enabled)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown module."
        )
    audit.record(
        db,
        operator,
        action="module.global_toggle",
        target=module_id,
        detail={"enabled": payload.enabled},
    )
    return result


@admin_router.put(
    "/modules/{module_id}/groups/{group}", response_model=schemas.AdminModule
)
def admin_set_group(
    module_id: str,
    payload: schemas.ModuleToggleRequest,
    group: str = Path(pattern="^(" + "|".join(ACCOUNT_TYPES) + ")$"),
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Assign or unassign one account group for one module. A group
    outside the vocabulary never reaches the handler (422)."""
    try:
        result = module_control.set_group_assignment(
            db, module_id, group, payload.enabled
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown module."
        )
    audit.record(
        db,
        operator,
        action="module.group_assignment",
        target=module_id,
        detail={"group": group, "enabled": payload.enabled},
    )
    return result


@admin_router.put(
    "/modules/{module_id}/tiers/{tier}", response_model=schemas.AdminModule
)
def admin_set_tier(
    module_id: str,
    payload: schemas.ModuleToggleRequest,
    tier: str = Path(pattern="^(" + "|".join(tiers.TIER_KEYS) + ")$"),
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Light or darken one account tier for one module — the
    staged-rollout switch (owner design, 2026-10-31): a module
    can be off for normal accounts yet on for moderator admins
    or beta testers while it is tested, then released tier by
    tier. A tier outside the vocabulary never reaches the
    handler (422). God has no switch — god always sees all.

    An off → on flip is a RELEASE (owner order, 2026-11-09):
    the audience's effectiveness is snapshotted BEFORE the flip,
    and afterwards module_release fires the badge, the scoped
    announcement, and the wizard pending rows for exactly the
    accounts that gained the module (nobody gained ⇒ no event).
    The release is a side effect of the flip the operator made —
    it never fails the flip itself, so it runs guarded, after
    the audit, and any surprise lands in the log, not the
    operator's face."""
    was_on = (
        module_control.tier_switches(db, module_id).get(tier, False)
        if payload.enabled
        else True
    )
    before = (
        module_release.effectiveness_snapshot(
            db, module_id, module_release.audience_for(db, tier)
        )
        if payload.enabled and not was_on
        else {}
    )
    try:
        result = module_control.set_tier_assignment(
            db, module_id, tier, payload.enabled
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown module."
        )
    audit.record(
        db,
        operator,
        action="module.tier_assignment",
        target=module_id,
        detail={"tier": tier, "enabled": payload.enabled},
    )
    if payload.enabled and not was_on:
        try:
            module_release.on_tier_opened(
                db,
                module_id=module_id,
                tier_key=tier,
                actor_id=operator.id,
                actor_name=operator.name,
                before=before,
            )
        except Exception:  # noqa: BLE001 — the flip already landed
            import logging

            logging.getLogger(__name__).exception(
                "module release event failed (module=%s tier=%s)",
                module_id,
                tier,
            )
    return result
