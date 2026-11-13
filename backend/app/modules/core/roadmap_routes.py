"""Roadmap routes (audit A15).

Public read hangs off the core router at GET /core/roadmap —
no auth, so the signed-out landing can link it. Operator CRUD
hangs off the admin router (require_operator + audit rows),
mirroring the directory admin surfaces.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_operator
from app.modules.core import audit, roadmap, schemas

public_router = APIRouter()
admin_router = APIRouter()


@public_router.get("/roadmap", response_model=list[schemas.RoadmapEntryView])
def public_roadmap(db: Session = Depends(get_db)):
    return [roadmap.entry_view(e) for e in roadmap.list_entries(db)]


@admin_router.get("/roadmap-entries", response_model=list[schemas.RoadmapEntryView])
def list_entries(
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return [roadmap.entry_view(e) for e in roadmap.list_entries(db)]


@admin_router.post(
    "/roadmap-entries",
    response_model=schemas.RoadmapEntryView,
    status_code=status.HTTP_201_CREATED,
)
def create_entry(
    payload: schemas.RoadmapEntryWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        entry = roadmap.create_entry(db, payload.model_dump())
    except roadmap.RoadmapError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    audit.record(
        db,
        actor=operator,
        action="roadmap.create",
        target=f"roadmap_entry:{entry.id}",
        detail={"title": entry.title, "status": entry.status},
    )
    return roadmap.entry_view(entry)


@admin_router.put("/roadmap-entries/{entry_id}", response_model=schemas.RoadmapEntryView)
def update_entry(
    entry_id: uuid.UUID,
    payload: schemas.RoadmapEntryWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    entry = roadmap.get_entry(db, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Roadmap entry not found."
        )
    try:
        entry = roadmap.update_entry(db, entry, payload.model_dump())
    except roadmap.RoadmapError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    audit.record(
        db,
        actor=operator,
        action="roadmap.update",
        target=f"roadmap_entry:{entry.id}",
        detail={"title": entry.title, "status": entry.status},
    )
    return roadmap.entry_view(entry)


@admin_router.delete("/roadmap-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: uuid.UUID,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    entry = roadmap.get_entry(db, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Roadmap entry not found."
        )
    audit.record(
        db,
        actor=operator,
        action="roadmap.delete",
        target=f"roadmap_entry:{entry.id}",
        detail={"title": entry.title},
    )
    roadmap.delete_entry(db, entry)
    return None
