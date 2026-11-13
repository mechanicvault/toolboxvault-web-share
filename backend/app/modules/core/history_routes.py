"""History & restore routes (user audit trail, 2026-10-19).

The user's own surface over core's change journal: restore
markers, the plain-language activity timeline, and the restore
engine. Everything is scoped to the CALLER's id — one account's
history is never readable through another account's token. The
operator's on-behalf surface lives in admin_routes (and writes
the admin audit log there).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.core import journal, schemas

router = APIRouter()


def entry_view(
    row, *, owner_id: uuid.UUID, self_word: str = "you"
) -> dict:
    """One timeline row. `actor` is relative to the account owner:
    the owner themselves, another person (peer/borrower), an
    operator acting from the admin panel, or the system."""
    if row.actor_id is None:
        actor = "system"
    elif row.actor_id == owner_id:
        actor = self_word
    else:
        actor = "other"
    return {
        "id": row.id,
        "seq": row.seq,
        "occurred_at": row.occurred_at,
        "module": row.module,
        "entity_type": row.entity_type,
        "action": row.action,
        "label": row.label,
        "restorable": row.restorable,
        "actor": actor,
    }


def marker_view(row) -> dict:
    return {
        "id": row.id,
        "label": row.label,
        "kind": row.kind,
        "journal_seq": row.journal_seq,
        "created_at": row.created_at,
    }


@router.get("/history/markers", response_model=list[schemas.RestoreMarkerView])
def list_markers(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [marker_view(m) for m in journal.list_markers(db, user.id)]


@router.post(
    "/history/markers",
    response_model=schemas.RestoreMarkerView,
    status_code=status.HTTP_201_CREATED,
)
def create_marker(
    payload: schemas.MarkerCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    marker = journal.create_marker(
        db, user.id, kind="manual", label=payload.label
    )
    return marker_view(marker)


@router.get("/history/entries", response_model=schemas.HistoryEntriesPage)
def list_entries(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows, total = journal.list_entries(db, user.id, limit=limit, offset=offset)
    return {
        "entries": [entry_view(r, owner_id=user.id) for r in rows],
        "total": total,
    }


def _own_marker_or_404(db: Session, user_id: uuid.UUID, marker_id: uuid.UUID):
    marker = journal.get_marker(db, user_id, marker_id)
    if marker is None:
        raise HTTPException(status_code=404, detail="Restore point not found.")
    return marker


@router.get(
    "/history/restore-preview", response_model=schemas.RestorePreviewView
)
def restore_preview(
    marker_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    marker = _own_marker_or_404(db, user.id, marker_id)
    return journal.restore_preview(db, user.id, marker)


@router.post("/history/restore", response_model=schemas.RestoreResultView)
def restore(
    payload: schemas.RestoreRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    marker = _own_marker_or_404(db, user.id, payload.marker_id)
    try:
        result = journal.restore_to_marker(
            db, user.id, marker, actor_id=user.id
        )
    except journal.RestoreConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "restore_conflict", "message": str(exc)},
        )
    return result
