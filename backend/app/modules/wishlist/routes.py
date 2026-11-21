"""Wishlist module routes. HTTP layer only — logic lives in
service.py. Every route is gated on the wishlist FEATURE module
being effective for the caller (require_module): seeded defaults
mechanic + shop.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.modules.inventory import service as inventory_service
from app.modules.wishlist import attachments, schemas, service

router = APIRouter()

_wishlist_module = require_module("wishlist")


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.WishlistNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "wishlist", "status": "ok"}


@router.get("/stats", response_model=schemas.WishlistStats)
def wishlist_stats(
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    """The Wishlist panel stat: items still wanted."""
    return service.stats(db, user.id)


@router.get("/items", response_model=list[schemas.WishlistItemPublic])
def list_items(
    q: str | None = None,
    status_filter: str | None = None,
    limit: int = 200,
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    items = service.list_items(db, user.id, q=q, status=status_filter, limit=limit)
    return [service.serialize_with_db(db, item) for item in items]


@router.post(
    "/items",
    response_model=schemas.WishlistItemPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_item(
    payload: schemas.WishlistItemCreate,
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    try:
        item = service.create_item(db, user.id, payload)
    except (service.WishlistError, inventory_service.ToolValidationError) as exc:
        raise _as_http(exc)
    return service.serialize_with_db(db, item)


@router.get("/items/{item_id}", response_model=schemas.WishlistItemPublic)
def get_item(
    item_id: uuid.UUID,
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    item = service.get_item(db, user.id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return service.serialize_with_db(db, item)


@router.put("/items/{item_id}", response_model=schemas.WishlistItemPublic)
def update_item(
    item_id: uuid.UUID,
    payload: schemas.WishlistItemUpdate,
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    try:
        item = service.update_item(db, user.id, item_id, payload)
    except (service.WishlistError, inventory_service.ToolValidationError) as exc:
        raise _as_http(exc)
    if item is None:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return service.serialize_with_db(db, item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id: uuid.UUID,
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    if not service.delete_item(db, user.id, item_id):
        raise HTTPException(status_code=404, detail="Wishlist item not found")


@router.post(
    "/items/{item_id}/mark-purchased",
    response_model=schemas.WishlistItemPublic,
)
def mark_purchased(
    item_id: uuid.UUID,
    payload: schemas.MarkPurchased,
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    try:
        item = service.mark_purchased(db, user.id, item_id, payload)
    except service.WishlistError as exc:
        raise _as_http(exc)
    if item is None:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return service.serialize_with_db(db, item)


@router.post(
    "/items/{item_id}/convert",
    response_model=schemas.ConvertResponse,
)
def convert_to_tool(
    item_id: uuid.UUID,
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    """Copy this purchased item into Asset Inventory as a tool.
    Creating a real tool passes through the two inventory doorways
    the inventory create route itself uses (parts-convert
    precedent): the inventory module must be effective for the
    caller, and the entitlement item-limit doorway applies."""
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
    if service.get_item(db, user.id, item_id) is None:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
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
        result = service.convert_to_tool(db, user.id, item_id)
    except service.WishlistError as exc:
        raise _as_http(exc)
    if result is None:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    item, tool = result
    return {"item": service.serialize_with_db(db, item), "tool_id": tool.id}


# -- uploads -------------------------------------------------------------------


@router.post(
    "/items/{item_id}/upload-url", response_model=schemas.UploadUrlResponse
)
def get_upload_url(
    item_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.issue_upload_url(db, user.id, item_id, payload)
    except attachments.WishlistUploadError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Wishlist item not found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=str(exc))


@router.post("/items/{item_id}/attachments", response_model=dict)
def attach_file(
    item_id: uuid.UUID,
    payload: schemas.AttachRequest,
    user: CurrentUser = Depends(_wishlist_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.attach_file(db, user.id, item_id, payload)
    except attachments.WishlistUploadError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Wishlist item not found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=str(exc))
