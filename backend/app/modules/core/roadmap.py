"""Operator-published roadmap (audit A15).

The "What's coming" page is operator content: entries are
created/edited ONLY from the admin panel, read publicly
(signed-out included). The table ships EMPTY — nothing is
seeded, because a roadmap is the operator's word, not code's.
"""

from sqlalchemy.orm import Session

from app.modules.core import models

STATUSES = ("planned", "in_progress", "shipped")


class RoadmapError(ValueError):
    pass


def entry_view(entry: models.RoadmapEntry) -> dict:
    return {
        "id": str(entry.id),
        "title": entry.title,
        "note": entry.note or "",
        "status": entry.status,
        "sort_order": entry.sort_order,
    }


def list_entries(db: Session) -> list[models.RoadmapEntry]:
    return (
        db.query(models.RoadmapEntry)
        .order_by(
            models.RoadmapEntry.sort_order.asc(),
            models.RoadmapEntry.created_at.asc(),
        )
        .all()
    )


def _validate(data: dict) -> None:
    title = (data.get("title") or "").strip()
    if not title:
        raise RoadmapError("A roadmap entry needs a title.")
    if data.get("status") not in STATUSES:
        raise RoadmapError(
            f"Status must be one of: {', '.join(STATUSES)}."
        )


def create_entry(db: Session, data: dict) -> models.RoadmapEntry:
    _validate(data)
    entry = models.RoadmapEntry(
        title=data["title"].strip(),
        note=(data.get("note") or "").strip(),
        status=data["status"],
        sort_order=int(data.get("sort_order") or 0),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_entry(db: Session, entry_id) -> models.RoadmapEntry | None:
    return db.get(models.RoadmapEntry, entry_id)


def update_entry(db: Session, entry: models.RoadmapEntry, data: dict) -> models.RoadmapEntry:
    _validate(data)
    entry.title = data["title"].strip()
    entry.note = (data.get("note") or "").strip()
    entry.status = data["status"]
    entry.sort_order = int(data.get("sort_order") or 0)
    db.commit()
    db.refresh(entry)
    return entry


def delete_entry(db: Session, entry: models.RoadmapEntry) -> None:
    db.delete(entry)
    db.commit()
