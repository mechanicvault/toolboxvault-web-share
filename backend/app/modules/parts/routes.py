"""Used Parts module routes. HTTP layer only — logic lives in service.py.

Every route is gated on the parts FEATURE module being effective for
the caller (module doctrine): global switch + dependency health +
one of the caller's groups assigned (seeded defaults: mechanic +
shop). A module that isn't effective answers 403
{code: module_unavailable} via require_module.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.modules.inventory import custom_fields
from app.modules.parts import attachments, models, pool, schemas, service

router = APIRouter()

_parts_module = require_module("parts")

_PAID_MESSAGE = (
    "Publishing to the Community Parts pool needs a paid plan. "
    "Your parts stay on your private shelf either way — upgrade "
    "to list them for the community."
)


def _publish_gate(db: Session, user_id: uuid.UUID) -> None:
    """The paid-publish refusal (community suite rule), in the
    item-cap doorway shape: 403 + a machine-readable code. Only
    bites while the entitlements enforcement switch is on — the
    check itself lives in pool.can_publish."""
    if not pool.can_publish(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "paid_plan_required", "message": _PAID_MESSAGE},
        )


def _candidate(
    *, category: str = "", visibility: str | None = None
) -> models.Part:
    """A transient part carrying only what visibility resolution
    reads — the gate's what-if for create/update."""
    return models.Part(
        owner_id=uuid.uuid4(), title="", category=category, visibility=visibility
    )


def _as_http(exc: Exception) -> HTTPException:
    """Part errors: not-found (incl. foreign ids) -> 404, friendly
    refusals -> 422. Custom-field validation errors are 422s too."""
    if isinstance(exc, service.PartNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "parts", "status": "ok"}


@router.get("/stats", response_model=schemas.PartsStats)
def parts_stats(
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    """The Used Parts home stat: entries on the shelf (+ units)."""
    return service.stats(db, user.id)


# -- locations ---------------------------------------------------------------


@router.get("/locations", response_model=list[schemas.PartLocationPublic])
def list_locations(
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    return service.list_locations(db, user.id)


@router.post(
    "/locations",
    response_model=schemas.PartLocationPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_location(
    payload: schemas.PartLocationCreate,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    try:
        location = service.create_location(db, user.id, payload)
    except service.PartError as exc:
        raise _as_http(exc)
    return service.serialize_location(db, user.id, location)


@router.put("/locations/{location_id}", response_model=schemas.PartLocationPublic)
def update_location(
    location_id: uuid.UUID,
    payload: schemas.PartLocationUpdate,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    try:
        location = service.update_location(db, user.id, location_id, payload)
    except service.PartError as exc:
        raise _as_http(exc)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    return service.serialize_location(db, user.id, location)


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(
    location_id: uuid.UUID,
    payload: schemas.PartLocationDelete | None = None,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    try:
        deleted = service.delete_location(
            db, user.id, location_id, payload or schemas.PartLocationDelete()
        )
    except service.PartError as exc:
        raise _as_http(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Location not found")


# -- parts ---------------------------------------------------------------------


@router.get("/parts", response_model=list[schemas.PartPublic])
def list_parts(
    q: str | None = None,
    location_id: uuid.UUID | None = None,
    condition: str | None = None,
    limit: int = 200,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    locations = service.owned_locations(db, user.id)
    parts = service.list_parts(
        db, user.id, q=q, location_id=location_id, condition=condition, limit=limit
    )
    return [service.serialize_part(db, part, locations) for part in parts]


@router.post(
    "/parts", response_model=schemas.PartPublic, status_code=status.HTTP_201_CREATED
)
def create_part(
    payload: schemas.PartCreate,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    # Publish gate: a part BORN public (its override, its
    # category's setting, or the pool default says so) is a
    # publish act — refused for a non-paid account while
    # enforcement is on, before anything is written.
    settings = pool.get_settings(db, user.id)
    candidate = _candidate(category=payload.category, visibility=payload.visibility)
    if pool.resolve_visibility(candidate, settings) == "public":
        _publish_gate(db, user.id)
    try:
        part = service.create_part(db, user.id, payload)
    except (service.PartError, custom_fields.FieldValidationError) as exc:
        raise _as_http(exc)
    return service.serialize_part(db, part)


@router.get("/parts/{part_id}", response_model=schemas.PartPublic)
def get_part(
    part_id: uuid.UUID,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    part = service.get_part(db, user.id, part_id)
    if part is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return service.serialize_part(db, part)


@router.put("/parts/{part_id}", response_model=schemas.PartPublic)
def update_part(
    part_id: uuid.UUID,
    payload: schemas.PartUpdate,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    # Publish gate on the MERGED state: an edit that would leave
    # this part public (a fresh override, a category move into a
    # public category, …) is a publish act.
    existing = service.get_part(db, user.id, part_id)
    if existing is not None:
        settings = pool.get_settings(db, user.id)
        changes = payload.model_dump(exclude_unset=True)
        candidate = _candidate(
            category=(
                changes["category"]
                if changes.get("category") is not None
                else existing.category
            ),
            visibility=(
                changes["visibility"]
                if "visibility" in changes
                else existing.visibility
            ),
        )
        if pool.resolve_visibility(candidate, settings) == "public":
            _publish_gate(db, user.id)
    try:
        part = service.update_part(db, user.id, part_id, payload)
    except (service.PartError, custom_fields.FieldValidationError) as exc:
        raise _as_http(exc)
    if part is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return service.serialize_part(db, part)


@router.delete("/parts/{part_id}", status_code=204)
def delete_part(
    part_id: uuid.UUID,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    if not service.delete_part(db, user.id, part_id):
        raise HTTPException(status_code=404, detail="Part not found")


@router.post("/parts/{part_id}/convert-to-tool", response_model=schemas.PartConvertResponse)
def convert_to_tool(
    part_id: uuid.UUID,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    """Copy this part into Asset Inventory as a tool. Creating a
    real tool means passing through the two inventory doorways the
    inventory create route itself uses: the module must be
    effective for the caller (parts itself doesn't depend on
    inventory, so this gate is checked here, explicitly), and the
    entitlement item-limit doorway applies exactly as if the tool
    were added by hand."""
    from app.modules.billing import entitlements
    from app.modules.core import module_control

    if not module_control.effective_for_user(db, "inventory", user.account_types, user_id=user.id, tier=user.tier, beta_tester=user.beta_tester):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "module_unavailable",
                "module": "inventory",
                "message": "Inventory isn't enabled for your account.",
            },
        )
    if service.get_part(db, user.id, part_id) is None:
        raise HTTPException(status_code=404, detail="Part not found")
    if not entitlements.can_add_tool(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "item_limit_reached",
                "message": (
                    "You've reached your plan's item limit. Upgrade to add "
                    "more tools — your existing tools stay safe and visible."
                ),
            },
        )
    try:
        result = service.convert_to_tool(db, user.id, part_id)
    except custom_fields.FieldValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    if result is None:
        raise HTTPException(status_code=404, detail="Part not found")
    part, tool = result
    return {"part": service.serialize_part(db, part), "tool_id": tool.id}


# -- uploads -------------------------------------------------------------------


@router.post("/parts/{part_id}/upload-url", response_model=schemas.UploadUrlResponse)
def get_upload_url(
    part_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.issue_upload_url(db, user.id, part_id, payload)
    except attachments.PartUploadError as exc:
        # A foreign/missing part is a 404 (ids don't leak); a bad
        # file is a 422 — the error copy distinguishes them.
        code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Part not found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=str(exc))


@router.post("/parts/{part_id}/attachments", response_model=dict)
def attach_file(
    part_id: uuid.UUID,
    payload: schemas.AttachRequest,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.attach_file(db, user.id, part_id, payload)
    except attachments.PartUploadError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Part not found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=str(exc))


# -- community pool (owner 2026-10-19) -----------------------------------------
#
# The owner's settings ride the parts module gate (they are the
# owner's own controls). The LISTINGS are different: the pool is
# the community's window — readable by every signed-in user
# regardless of group, and by logged-out visitors through the
# /public twin. Both read routes answer the identical exact-key
# listing payload (pool.serialize_listing), and both 404 while
# the operator's pool switch (or the parts global switch) is off:
# hidden entirely means hidden.


@router.get("/pool/settings", response_model=schemas.PoolSettingsPublic)
def get_pool_settings(
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    return pool.settings_view(pool.get_settings(db, user.id))


@router.put("/pool/settings", response_model=schemas.PoolSettingsPublic)
def update_pool_settings(
    payload: schemas.PoolSettingsUpdate,
    user: CurrentUser = Depends(_parts_module),
    db: Session = Depends(get_db),
):
    settings = pool.get_settings(db, user.id)
    changes = payload.model_dump(exclude_unset=True)
    new_default = changes.get("default_visibility", settings.default_visibility)
    new_categories = settings.category_visibility or {}
    if changes.get("category_visibility") is not None:
        new_categories = dict(changes["category_visibility"])
        for label, value in new_categories.items():
            if value not in pool.VISIBILITIES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Category “{label}” must be 'public' or 'private'."
                    ),
                )
    # Publish gate on the RESULT: a settings write that would
    # leave ANY of the owner's parts public is a publish act.
    from app.modules.parts import models as part_models

    probe = part_models.PartPoolSettings(
        owner_id=user.id,
        default_visibility=new_default,
        category_visibility=new_categories,
    )
    if pool.would_publish_count(db, user.id, probe) > 0:
        _publish_gate(db, user.id)
    settings.default_visibility = new_default
    settings.category_visibility = new_categories
    db.commit()
    db.refresh(settings)
    return pool.settings_view(settings)


def _community(
    db: Session,
    q: str | None,
    year: int | None,
    make: str | None,
    model: str | None,
    engine: str | None,
    category: str | None,
    seller_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> list[dict]:
    if not pool.pool_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The Community Parts pool isn't available right now.",
        )
    return pool.search_listings(
        db,
        q=q,
        year=year,
        make=make,
        model=model,
        engine=engine,
        category=category,
        seller_id=seller_id,
        limit=limit,
        offset=offset,
    )


@router.get("/community", response_model=list[schemas.CommunityListingPublic])
def community_listings(
    q: str | None = None,
    year: int | None = None,
    make: str | None = None,
    model: str | None = None,
    engine: str | None = None,
    category: str | None = None,
    seller_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """The pool for signed-in users — deliberately NOT behind the
    parts module gate: every group browses the community shelf,
    including accounts the shelf itself isn't assigned to."""
    return _community(db, q, year, make, model, engine, category, seller_id, limit, offset)


@router.get(
    "/public/community", response_model=list[schemas.CommunityListingPublic]
)
def public_community_listings(
    q: str | None = None,
    year: int | None = None,
    make: str | None = None,
    model: str | None = None,
    engine: str | None = None,
    category: str | None = None,
    seller_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """The logged-out window onto the same pool: the identical
    exact-key listing payload, nothing else. Contact actions do
    not exist here — messaging requires an account."""
    return _community(db, q, year, make, model, engine, category, seller_id, limit, offset)
