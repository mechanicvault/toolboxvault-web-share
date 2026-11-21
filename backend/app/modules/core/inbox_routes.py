"""In-app notification routes (core module), mounted on the core
router at /notifications.

The header ticker and the home Notifications block have consumed
GET /api/core/notifications since they were built — the ticker
requires a bare JSON array of {id, text, tone?}; list_for_user's
view supplies exactly that plus title/body/data for richer surfaces.
Everything is owner-scoped through the caller's own id: there is no
way to name another user's inbox here.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from pydantic import BaseModel

from app.modules.core import content_alerts, inbox, notification_prefs, schemas

router = APIRouter()


@router.get(
    "/me/notification-preferences",
    response_model=list[schemas.NotificationChannelPrefView],
)
def list_notification_preferences(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """My notification channel preferences: every category with
    its effective email state (Settings -> Notifications)."""
    return notification_prefs.preferences_view(db, user.id)


@router.put(
    "/me/notification-preferences",
    response_model=schemas.NotificationChannelPrefView,
)
def set_notification_preference(
    payload: schemas.NotificationChannelPrefUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Flip one category's channel for me. Unknown categories
    are a 422 — the category list is a closed vocabulary owned
    by notification_prefs."""
    if payload.category not in notification_prefs.CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown notification category: {payload.category}",
        )
    notification_prefs.set_channel_pref(
        db,
        user.id,
        category=payload.category,
        channel=payload.channel,
        enabled=payload.enabled,
    )
    return {
        "category": payload.category,
        "email_enabled": notification_prefs.channel_enabled(
            db, user.id, payload.category, notification_prefs.CHANNEL_EMAIL
        ),
    }


class ContentAlertPrefsView(BaseModel):
    """My new-content inbox opt-ins: both boxes,
    default OFF (see content_alerts.get_prefs)."""

    downloads: bool
    prints: bool


class ContentAlertPrefUpdate(BaseModel):
    kind: str
    enabled: bool


@router.get("/me/content-alerts", response_model=ContentAlertPrefsView)
def get_content_alerts(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """My new-content opt-ins: the Downloads page box, the
    3D Print Files box, and their Settings -> Notifications
    mirror all read this one answer."""
    return content_alerts.get_prefs(db, user.id)


@router.put("/me/content-alerts", response_model=ContentAlertPrefsView)
def put_content_alert(
    payload: ContentAlertPrefUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Flip ONE new-content box for me. The kind vocabulary is
    closed ("downloads" | "prints") — anything else is a 422."""
    if payload.kind not in ("downloads", "prints"):
        raise HTTPException(
            status_code=422,
            detail=f"Unknown content-alert kind: {payload.kind}",
        )
    return content_alerts.set_pref(
        db, user.id, kind=payload.kind, enabled=payload.enabled
    )


@router.get("/notifications", response_model=list[schemas.NotificationPublic])
def list_notifications(
    limit: int = inbox.DEFAULT_LIMIT,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """My notifications from the past 30 days, newest first, as a
    bare array (the ticker contract). limit/offset page through
    the window; the default page is generous."""
    return inbox.list_for_user(db, user.id, limit=limit, offset=offset)


class NotificationSummaryView(BaseModel):
    """Unread alert counts per badge surface (sheet row 62):
    the left menu's red count badges and the Home widgets'
    urgency flags read this one answer. Only surfaces with a
    live count appear in `counts`."""

    counts: dict[str, int]
    total: int


@router.get("/notifications/summary", response_model=NotificationSummaryView)
def notification_summary(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """My unread alert counts, grouped by the surface that
    deals with them. Derived from the inbox on every call —
    marking notifications read is what clears a badge."""
    return inbox.alert_summary(db, user.id)


class TabBadgesView(BaseModel):
    """The counts behind the tab bubbles (sheet row 190): unread
    notifications for the Claims / Maintenance / Disaster tabs,
    the Borrowing tab's unread notes plus its live overdue
    checkout ids, and the Health Check tab's live issue count."""

    claims: int
    maintenance: int
    disaster: int
    borrowing: int
    borrowing_overdue_ids: list[str]
    health: int


@router.get("/notifications/tab-badges", response_model=TabBadgesView)
def notification_tab_badges(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """My tab bubble counts. Derived on every call — the Health
    count is the live scan (it stays until the items are fixed);
    the others drop as their notifications are marked read."""
    return inbox.tab_badges(db, user.id)


class ReadTabRequest(BaseModel):
    tab: str


@router.post("/notifications/read-tab", response_model=schemas.ReadAllResponse)
def mark_tab_notifications_read(
    payload: ReadTabRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all of MY unread notifications for one tab read —
    clicking the tab clears its bubble. The tab vocabulary is
    closed (claims | maintenance | disaster | borrowing) —
    anything else is a 422."""
    if payload.tab not in inbox.TAB_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown tab: {payload.tab}",
        )
    return {"updated": inbox.mark_tab_read(db, user.id, payload.tab)}


@router.post("/notifications/{notification_id}/read", status_code=204)
def mark_notification_read(
    notification_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark one of MY notifications read. A foreign id is a 404,
    indistinguishable from a nonexistent one."""
    if not inbox.mark_read(db, user.id, notification_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That notification doesn't exist.",
        )


@router.delete("/notifications/{notification_id}", status_code=204)
def delete_notification(
    notification_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete one of MY notifications. A foreign id is a 404,
    indistinguishable from a nonexistent one."""
    if not inbox.delete_for_user(db, user.id, notification_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That notification doesn't exist.",
        )


@router.post("/notifications/read-all", response_model=schemas.ReadAllResponse)
def mark_all_notifications_read(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark my whole inbox read; answers how many rows changed."""
    return {"updated": inbox.mark_all_read(db, user.id)}
