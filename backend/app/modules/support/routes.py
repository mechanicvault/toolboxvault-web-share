"""Support ticket routes. HTTP layer only — logic lives in
service.py.

Two routers:

- `router` (the manifest router, mounted at /api/support): the
  member face. Every route rides the support FEATURE module gate
  (require_module), and the service scopes everything to the
  caller's own tickets — a foreign id is a 404, never an oracle.
- `admin_router` (mounted by main.py at /api/admin): the support
  desk. Operator-only on every route; replies and status changes
  are audited (the module_routes pattern — audit.record after the
  change commits).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module, require_operator
from app.modules.core import audit
from app.modules.support import schemas, service

router = APIRouter()
admin_router = APIRouter()

_support_module = require_module("support")


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.SupportNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "support", "status": "ok"}


# -- member face ------------------------------------------------------------------------


@router.get("/stats", response_model=schemas.SupportStats)
def support_stats(
    user: CurrentUser = Depends(_support_module),
    db: Session = Depends(get_db),
):
    """The Open tickets panel stat: my tickets not yet closed."""
    return service.stats(db, user.id)


@router.post(
    "/tickets",
    response_model=schemas.TicketDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_ticket(
    payload: schemas.TicketCreate,
    user: CurrentUser = Depends(_support_module),
    db: Session = Depends(get_db),
):
    try:
        return service.create_ticket(
            db, user, subject=payload.subject, body=payload.body
        )
    except service.SupportError as exc:
        raise _as_http(exc)


@router.get("/tickets", response_model=list[schemas.TicketSummary])
def my_tickets(
    user: CurrentUser = Depends(_support_module),
    db: Session = Depends(get_db),
):
    """My tickets only, newest activity first."""
    return service.list_my_tickets(db, user.id)


@router.get("/tickets/{ticket_id}", response_model=schemas.TicketDetail)
def my_ticket(
    ticket_id: uuid.UUID,
    user: CurrentUser = Depends(_support_module),
    db: Session = Depends(get_db),
):
    try:
        return service.get_my_ticket(db, user.id, ticket_id)
    except service.SupportError as exc:
        raise _as_http(exc)


@router.post("/tickets/{ticket_id}/messages", response_model=schemas.TicketDetail)
def reply_to_ticket(
    ticket_id: uuid.UUID,
    payload: schemas.MessageWrite,
    user: CurrentUser = Depends(_support_module),
    db: Session = Depends(get_db),
):
    try:
        return service.add_user_message(db, user, ticket_id, body=payload.body)
    except service.SupportError as exc:
        raise _as_http(exc)


@router.get("/videos", response_model=list[schemas.HelpVideoPublic])
def published_videos(
    user: CurrentUser = Depends(_support_module),
    db: Session = Depends(get_db),
):
    """The How-to videos tab's list: published walkthroughs
    only (drafts are the operator face's, below)."""
    return service.list_published_videos(db)


# -- operator face (support desk) ----------------------------------------------------------


@admin_router.get("/support/tickets", response_model=list[schemas.AdminTicketSummary])
def admin_list_tickets(
    status_filter: str = Query(default="", alias="status"),
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Every ticket, newest activity first; ?status= filters."""
    try:
        return service.list_all_tickets(db, status_filter)
    except service.SupportError as exc:
        raise _as_http(exc)


@admin_router.get(
    "/support/tickets/{ticket_id}", response_model=schemas.AdminTicketDetail
)
def admin_get_ticket(
    ticket_id: uuid.UUID,
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        return service.get_ticket_admin(db, ticket_id)
    except service.SupportError as exc:
        raise _as_http(exc)


@admin_router.post(
    "/support/tickets/{ticket_id}/messages",
    response_model=schemas.AdminTicketDetail,
)
def admin_reply(
    ticket_id: uuid.UUID,
    payload: schemas.MessageWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Operator reply: moves the ticket to under review and
    notifies the owner (in the reply's own commit, in the
    service)."""
    try:
        result = service.add_operator_message(
            db, operator, ticket_id, body=payload.body
        )
    except service.SupportError as exc:
        raise _as_http(exc)
    audit.record(
        db,
        operator,
        action="support.reply",
        target=str(ticket_id),
        detail={"ticket_id": str(ticket_id)},
    )
    return result


@admin_router.post(
    "/support/tickets/{ticket_id}/status",
    response_model=schemas.AdminTicketDetail,
)
def admin_set_status(
    ticket_id: uuid.UUID,
    payload: schemas.StatusWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        result = service.set_status(db, operator, ticket_id, status=payload.status)
    except service.SupportError as exc:
        raise _as_http(exc)
    audit.record(
        db,
        operator,
        action="support.status",
        target=str(ticket_id),
        detail={"ticket_id": str(ticket_id), "status": payload.status},
    )
    return result


# -- operator face (how-to videos) ---------------------------------------------------------


@admin_router.get("/support/videos", response_model=list[schemas.AdminHelpVideo])
def admin_list_videos(
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Every video on the list, drafts included."""
    return service.list_all_videos(db)


@admin_router.post(
    "/support/videos",
    response_model=schemas.AdminHelpVideo,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_video(
    payload: schemas.HelpVideoWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        result = service.create_video(
            db,
            title=payload.title,
            summary=payload.summary,
            youtube=payload.youtube,
            section=payload.section,
            sort_order=payload.sort_order,
            is_published=payload.is_published,
        )
    except service.SupportError as exc:
        raise _as_http(exc)
    audit.record(
        db,
        operator,
        action="support.video_create",
        target=str(result["id"]),
        detail={"video_id": str(result["id"]), "section": payload.section},
    )
    return result


@admin_router.put(
    "/support/videos/{video_id}", response_model=schemas.AdminHelpVideo
)
def admin_update_video(
    video_id: uuid.UUID,
    payload: schemas.HelpVideoWrite,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        result = service.update_video(
            db,
            video_id,
            title=payload.title,
            summary=payload.summary,
            youtube=payload.youtube,
            section=payload.section,
            sort_order=payload.sort_order,
            is_published=payload.is_published,
        )
    except service.SupportError as exc:
        raise _as_http(exc)
    audit.record(
        db,
        operator,
        action="support.video_update",
        target=str(video_id),
        detail={"video_id": str(video_id), "section": payload.section},
    )
    return result


@admin_router.delete(
    "/support/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT
)
def admin_delete_video(
    video_id: uuid.UUID,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        service.delete_video(db, video_id)
    except service.SupportError as exc:
        raise _as_http(exc)
    audit.record(
        db,
        operator,
        action="support.video_delete",
        target=str(video_id),
        detail={"video_id": str(video_id)},
    )
    return None
