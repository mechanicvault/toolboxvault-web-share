"""Locate User Manual routes (wave 4) — mounted into the
INVENTORY router (the surfaces live on tool/battery pages), but
owned by the catalog module: the search/import machinery is
catalog's, and the doorway checks BOTH modules (an operator who
disables the catalog disables manual lookup with it).

  POST /tools/{id}/locate-manual          -> {candidates, links, charged}
  POST /batteries/{id}/locate-manual      -> {candidates, links, charged}
  POST /manual-lookup                     -> {candidates, links, charged}
       (the Add wizard: brand + model from the draft, no item
       exists yet — the pick is imported through the ordinary
       import route the moment the item is created)
  POST /tools/{id}/locate-manual/import   -> {attachment, already_present}
  POST /batteries/{id}/locate-manual/import
  POST /tools/{id}/locate-manual/import-link -> {attachment, already_present}
  POST /batteries/{id}/locate-manual/import-link

Nothing auto-imports: search returns candidates, the user picks,
import downloads + stores the file into the item's Manuals. The
import-link flow (owner ruling 2026-11-03) is the paste-an-
address variant: the server fetches the pasted URL itself —
PDFs only — and files the downloaded bytes as a manual.

Searches carry a per-user request budget (core.rate_limit):
each one fans out to public engines and document hosts.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.core.rate_limit import manual_lookup_rate_limiter
from app.modules.billing import wallet
from app.modules.catalog import manuals
from app.modules.inventory import service as inventory_service

router = APIRouter()

_doorway = require_module("catalog")
_inventory_doorway = require_module("inventory")


def _search_budget(user: CurrentUser) -> None:
    """One search = one hit against the caller's hourly budget."""
    key = f"manual-lookup:{user.id}"
    retry_after = manual_lookup_rate_limiter.retry_after(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "You've run a lot of manual searches in the last "
                "hour — give it a little while and try again."
            ),
            headers={"Retry-After": str(retry_after)},
        )
    manual_lookup_rate_limiter.record_hit(key)


class ManualImportRequest(BaseModel):
    source_url: str = Field(min_length=8, max_length=4000)
    source_name: str = Field(default="", max_length=200)


class ManualLinkRequest(BaseModel):
    url: str = Field(min_length=3, max_length=4000)


def _item_or_404(db: Session, user: CurrentUser, kind: str, item_id: uuid.UUID):
    getter = (
        inventory_service.get_tool if kind == "tools" else inventory_service.get_battery
    )
    item = getter(db, user.id, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found."
        )
    return item


def _search(kind: str, item_id: uuid.UUID, user: CurrentUser, db: Session):
    _search_budget(user)
    item = _item_or_404(db, user, kind, item_id)
    try:
        return manuals.locate(db, user, kind, item)
    except wallet.InsufficientCredits as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "insufficient_credits",
                "message": "Your AI credit balance doesn't cover this lookup.",
            },
        ) from exc


class ManualSearchRequest(BaseModel):
    brand: str = Field(default="", max_length=120)
    model: str = Field(default="", max_length=120)


@router.post("/manual-lookup")
def search_manuals_for_draft(
    payload: ManualSearchRequest,
    user: CurrentUser = Depends(_doorway),
    _inv: CurrentUser = Depends(_inventory_doorway),
    db: Session = Depends(get_db),
):
    """The wizard's search door: brand + model from the draft
    (at least one must be typed — an empty search names
    nothing). Same machinery, same budget, same charge."""
    if not payload.brand.strip() and not payload.model.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Type the brand or model first, then search.",
        )
    _search_budget(user)
    try:
        return manuals.find_manuals(
            db, user, payload.brand.strip(), payload.model.strip()
        )
    except wallet.InsufficientCredits as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "insufficient_credits",
                "message": "Your AI credit balance doesn't cover this lookup.",
            },
        ) from exc


def _import(kind: str, item_id: uuid.UUID, payload: ManualImportRequest, user, db):
    item = _item_or_404(db, user, kind, item_id)
    try:
        attachment, created = manuals.import_manual(
            db, user, kind, item, payload.source_url, payload.source_name
        )
    except manuals.ManualError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    view = next(
        (
            entry
            for entry in inventory_service.serialize_attachments(item)
            if entry["key"] == attachment["key"]
        ),
        attachment,
    )
    return {"attachment": view, "already_present": not created}


def _import_link(kind: str, item_id: uuid.UUID, payload: ManualLinkRequest, user, db):
    item = _item_or_404(db, user, kind, item_id)
    try:
        attachment, created = manuals.import_manual_from_link(
            db, user, kind, item, payload.url
        )
    except manuals.ManualError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    view = next(
        (
            entry
            for entry in inventory_service.serialize_attachments(item)
            if entry["key"] == attachment["key"]
        ),
        attachment,
    )
    return {"attachment": view, "already_present": not created}


@router.post("/tools/{tool_id}/locate-manual")
def locate_tool_manual(
    tool_id: uuid.UUID,
    user: CurrentUser = Depends(_doorway),
    _inv: CurrentUser = Depends(_inventory_doorway),
    db: Session = Depends(get_db),
):
    return _search("tools", tool_id, user, db)


@router.post("/batteries/{battery_id}/locate-manual")
def locate_battery_manual(
    battery_id: uuid.UUID,
    user: CurrentUser = Depends(_doorway),
    _inv: CurrentUser = Depends(_inventory_doorway),
    db: Session = Depends(get_db),
):
    return _search("batteries", battery_id, user, db)


@router.post("/tools/{tool_id}/locate-manual/import")
def import_tool_manual(
    tool_id: uuid.UUID,
    payload: ManualImportRequest,
    user: CurrentUser = Depends(_doorway),
    _inv: CurrentUser = Depends(_inventory_doorway),
    db: Session = Depends(get_db),
):
    return _import("tools", tool_id, payload, user, db)


@router.post("/tools/{tool_id}/locate-manual/import-link")
def import_tool_manual_link(
    tool_id: uuid.UUID,
    payload: ManualLinkRequest,
    user: CurrentUser = Depends(_doorway),
    _inv: CurrentUser = Depends(_inventory_doorway),
    db: Session = Depends(get_db),
):
    return _import_link("tools", tool_id, payload, user, db)


@router.post("/batteries/{battery_id}/locate-manual/import-link")
def import_battery_manual_link(
    battery_id: uuid.UUID,
    payload: ManualLinkRequest,
    user: CurrentUser = Depends(_doorway),
    _inv: CurrentUser = Depends(_inventory_doorway),
    db: Session = Depends(get_db),
):
    return _import_link("batteries", battery_id, payload, user, db)


@router.post("/batteries/{battery_id}/locate-manual/import")
def import_battery_manual(
    battery_id: uuid.UUID,
    payload: ManualImportRequest,
    user: CurrentUser = Depends(_doorway),
    _inv: CurrentUser = Depends(_inventory_doorway),
    db: Session = Depends(get_db),
):
    return _import("batteries", battery_id, payload, user, db)
