"""Admin announcements routes (release machinery, 2026-11-08):
the composer + history behind Admin -> Announcements.

Mounted by main.py at /api/admin alongside the other admin
routers. The gate is require_user_manager — god and moderator
admins, the two rungs the owner's release rule empowers to
speak to the whole user base (the rest of /api/admin's settings
and switches stay operator-only; this surface grants no other
power). Every compose writes an audit row after it lands.

There is deliberately NO update or delete route: a sent (or
queued) announcement can never be edited or re-sent from this
surface — a correction is a new announcement.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_user_manager
from app.modules.core import announcements, audit, inbox_links

router = APIRouter()


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=1000)
    link: str | None = Field(default=None, max_length=300)
    # Per-language parts (single-language rule, owner
    # 2026-11-10): optional — the stored title/body above stay
    # the English rendering the history reads; these parts are
    # what the fan-out gives each member, inbox and email
    # alike, in their own set language.
    title_es: str | None = Field(default=None, max_length=200)
    body_en: str | None = Field(default=None, max_length=1000)
    body_es: str | None = Field(default=None, max_length=1000)

    @field_validator("title", "body")
    @classmethod
    def _strip_and_require(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank.")
        return value

    @field_validator("link")
    @classmethod
    def _link_must_be_internal(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not inbox_links.is_internal_path(value):
            raise ValueError(
                "Link must be an in-app path (starting with /) — "
                "announcements never send users off the site."
            )
        return value


class AnnouncementView(BaseModel):
    id: str
    title: str
    body: str
    title_es: str | None = None
    body_en: str | None = None
    body_es: str | None = None
    link: str | None
    status: str
    recipient_count: int | None
    created_by_id: str | None
    created_by_name: str
    created_at: datetime
    sent_at: datetime | None


@router.get("/announcements", response_model=list[AnnouncementView])
def list_announcements(
    limit: int = Query(default=50, ge=1, le=200),
    _manager: CurrentUser = Depends(require_user_manager),
    db: Session = Depends(get_db),
):
    """The announcement history, newest first — what was sent,
    when, by whom, and to how many."""
    return announcements.list_announcements(db, limit=limit)


@router.post(
    "/announcements", response_model=AnnouncementView, status_code=201
)
def compose_announcement(
    payload: AnnouncementCreate,
    manager: CurrentUser = Depends(require_user_manager),
    db: Session = Depends(get_db),
):
    """Queue an announcement to ALL current users. The fan-out
    itself runs on the announcements job (minute cadence), never
    in this request — the response is the queued history row."""
    row = announcements.queue_announcement(
        db,
        author_id=manager.id,
        author_name=manager.name,
        title=payload.title,
        body=payload.body,
        link=payload.link,
        title_es=payload.title_es,
        body_en=payload.body_en,
        body_es=payload.body_es,
    )
    audit.record(
        db,
        manager,
        action="announcement.create",
        target=str(row.id),
        detail={"title": row.title, "link": row.link},
    )
    return announcements.announcement_view(row)
