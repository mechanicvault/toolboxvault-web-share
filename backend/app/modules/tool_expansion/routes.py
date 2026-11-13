"""Tool Expansion module routes. HTTP layer only — the matching
lives in service.py. Every route is gated on the tool_expansion
FEATURE module being effective for the caller (require_module):
seeded defaults mechanic + shop.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.modules.tool_expansion import schemas, service

router = APIRouter()

_expansion_module = require_module("tool_expansion")


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "tool_expansion", "status": "ok"}


@router.get("/suggestions", response_model=schemas.ExpansionSuggestions)
def list_suggestions(
    kind: str | None = None,
    item_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(_expansion_module),
    db: Session = Depends(get_db),
):
    """Every live suggestion, grouped by the caller's own item it
    expands. `kind` + `item_id` scope the answer to one item (the
    inventory badge and the item pages land here)."""
    if (kind is None) != (item_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="kind and item_id go together.",
        )
    if kind is not None and kind not in ("tool", "battery"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="kind must be tool or battery.",
        )
    return service.suggestions(db, user.id, kind=kind, item_id=item_id)


@router.get("/summary", response_model=schemas.ExpansionSummary)
def summary(
    user: CurrentUser = Depends(_expansion_module),
    db: Session = Depends(get_db),
):
    """The Home widget's read: the live count + the first few
    suggestions."""
    return service.summary(db, user.id)


@router.get("/counts", response_model=schemas.ExpansionCounts)
def counts(
    user: CurrentUser = Depends(_expansion_module),
    db: Session = Depends(get_db),
):
    """Per-item live suggestion counts for the inventory badges:
    {"tool:<id>": n, "battery:<id>": n} — items with none are
    absent from the map."""
    return service.counts(db, user.id)


@router.post("/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(
    payload: schemas.DismissIn,
    user: CurrentUser = Depends(_expansion_module),
    db: Session = Depends(get_db),
):
    """Move to archived matches: this suggestion, on this item
    of mine, leaves the Matches tab and waits in the caller's
    archive (GET /archived) until brought back (/unarchive)."""
    try:
        service.dismiss(
            db,
            user.id,
            anchor_kind=payload.anchor_kind,
            anchor_id=payload.anchor_id,
            suggested_model=payload.suggested_model,
        )
    except service.ExpansionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )


@router.get("/archived", response_model=schemas.ArchivedExpansions)
def list_archived(
    user: CurrentUser = Depends(_expansion_module),
    db: Session = Depends(get_db),
):
    """Archived matches: the caller's own dismissal ledger read
    back (main tab layout lane 5) — the matches they moved out of
    the Matches tab, each resolvable to a name/model from the
    live derivation where it still generates."""
    return service.archived(db, user.id)


@router.post("/unarchive", status_code=status.HTTP_204_NO_CONTENT)
def unarchive(
    payload: schemas.DismissIn,
    user: CurrentUser = Depends(_expansion_module),
    db: Session = Depends(get_db),
):
    """Bring one archived match back: delete the caller's ledger
    row (the inverse of /dismiss). If the match still generates,
    it returns to the Matches tab on the next read."""
    try:
        service.unarchive(
            db,
            user.id,
            anchor_kind=payload.anchor_kind,
            anchor_id=payload.anchor_id,
            suggested_model=payload.suggested_model,
        )
    except service.ExpansionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )


@router.post("/report", status_code=status.HTTP_204_NO_CONTENT)
def report(
    payload: schemas.ReportIn,
    user: CurrentUser = Depends(_expansion_module),
    db: Session = Depends(get_db),
):
    """Not relevant / inaccurate: judge the MATCH (anchor model ↔
    suggested model). Hides it for the reporter at once; at the
    kill threshold of distinct reporters it stops for everyone."""
    try:
        service.report(
            db,
            user.id,
            anchor_model=payload.anchor_model,
            suggested_model=payload.suggested_model,
        )
    except service.ExpansionNotFound as exc:
        # Same error, same answer as /dismiss (deep audit round 2,
        # C-16): ExpansionNotFound means "that suggestion/match
        # doesn't exist for you" on both routes — 404.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
