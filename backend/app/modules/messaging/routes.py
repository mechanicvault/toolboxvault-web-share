"""Messaging routes. HTTP layer only — logic lives in service.py
(threads, quarantine, blocks, moderation) and spam.py (the
firewall).

Every user route is gated on the messaging FEATURE module being
effective for the caller (module doctrine) — switch the module off
and the whole surface answers 403 {code: module_unavailable}. The
one exception is the public seller profile: it is read by the
community surfaces (including logged-out pool visitors), so it
checks only the module's GLOBAL switch, never a group assignment.

The moderation queue rides the community ROLE LADDER
(user | moderator | community_admin) plus operators — a
moderator is not an operator, and the admin panel is not the
queue's home.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, require_module
from app.modules.core import module_control
from app.modules.messaging import schemas, service

router = APIRouter()

_messaging_module = require_module("messaging")

_MODERATOR_ROLES = ("moderator", "community_admin")


def require_moderator(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """The moderation queue's gate: role-ladder moderators and
    community admins, plus operators (who hold every door)."""
    if user.is_operator or user.role in _MODERATOR_ROLES:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Moderator access only.",
    )


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.RateLimited):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, service.MessagingNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _participant(db: Session, user: CurrentUser, thread_id: uuid.UUID):
    try:
        return service.participant_thread(db, user.id, thread_id)
    except service.MessagingError as exc:
        raise _as_http(exc)


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "messaging", "status": "ok"}


# -- threads --------------------------------------------------------------------


@router.get("/threads", response_model=list[schemas.ThreadPublic])
def list_threads(
    folder: str = "inbox",
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    if folder not in ("inbox", "requests"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Folder must be 'inbox' or 'requests'.",
        )
    return service.list_threads(db, user.id, folder)


@router.get("/lookup", response_model=schemas.RecipientLookup)
def lookup_recipient(
    account_number: str,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    """Start-a-conversation lookup: an EXACT account number
    resolves to a name + id, nothing else (no enumeration)."""
    try:
        return service.lookup_recipient(db, account_number)
    except service.MessagingError as exc:
        raise _as_http(exc)


@router.get("/unread", response_model=schemas.UnreadSummary)
def unread_summary(
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    return service.unread_summary(db, user.id)


@router.post(
    "/threads",
    response_model=schemas.ThreadDetail,
    status_code=status.HTTP_201_CREATED,
)
def open_thread(
    payload: schemas.ThreadOpen,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    """Open (or continue) a conversation, posting the first
    message through the firewall. A "part" anchor must name a
    part that is PUBLIC in the Community Parts pool and owned by
    the recipient — you message a seller about their listing."""
    anchor_title = ""
    if payload.anchor_type == "part":
        from app.modules.parts import pool

        listing = pool.get_public_listing_part(db, payload.anchor_id)
        if listing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That listing isn't available.",
            )
        part, _settings = listing
        if part.owner_id != payload.recipient_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That listing belongs to someone else.",
            )
        anchor_title = part.title
    elif payload.anchor_type == "listing":
        from app.modules.marketplace import service as marketplace_service

        sale_listing = marketplace_service.get_public_listing(db, payload.anchor_id)
        if sale_listing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That listing isn't available.",
            )
        if sale_listing.owner_id != payload.recipient_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That listing belongs to someone else.",
            )
        anchor_title = sale_listing.title
    elif payload.anchor_type == "warranty_request":
        from app.modules.dealers import warranty as dealers_warranty

        request = dealers_warranty.get_request(db, payload.anchor_id)
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That warranty request isn't available.",
            )
        # A warranty conversation is strictly between the requester
        # and an agent on the request (routed or claiming) — nobody
        # else can anchor a thread to it, in either direction.
        sender_is_requester = request.requester_id == user.id
        recipient_is_requester = request.requester_id == payload.recipient_id
        sender_is_agent = dealers_warranty.is_party(db, request, user.id) and not sender_is_requester
        recipient_is_agent = dealers_warranty.is_party(db, request, payload.recipient_id) and not recipient_is_requester
        if not (
            (sender_is_requester and recipient_is_agent)
            or (sender_is_agent and recipient_is_requester)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That warranty request isn't between you two.",
            )
        anchor_title = f"Warranty: {request.item_name}"
    elif payload.anchor_type != "":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown anchor type.",
        )
    try:
        thread = service.open_thread(
            db,
            user,
            payload.recipient_id,
            payload.body,
            anchor_type=payload.anchor_type,
            anchor_id=payload.anchor_id,
            anchor_title=anchor_title,
        )
    except service.MessagingError as exc:
        raise _as_http(exc)
    return service.thread_view(db, user.id, thread)


@router.get("/threads/{thread_id}", response_model=schemas.ThreadDetail)
def get_thread(
    thread_id: uuid.UUID,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    thread = _participant(db, user, thread_id)
    return service.thread_view(db, user.id, thread)


@router.post("/threads/{thread_id}/read", response_model=schemas.ThreadPublic)
def mark_read(
    thread_id: uuid.UUID,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    thread = _participant(db, user, thread_id)
    service.mark_read(db, user.id, thread)
    return service.serialize_thread(db, user.id, thread)


@router.post("/threads/{thread_id}/messages", response_model=schemas.MessagePublic)
def post_message(
    thread_id: uuid.UUID,
    payload: schemas.MessageSend,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    thread = _participant(db, user, thread_id)
    try:
        message = service.post_message(db, user, thread, payload.body)
    except service.MessagingError as exc:
        raise _as_http(exc)
    return service.serialize_message(user.id, thread, message)


@router.post("/threads/{thread_id}/accept", response_model=schemas.ThreadPublic)
def accept_request(
    thread_id: uuid.UUID,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    thread = _participant(db, user, thread_id)
    try:
        thread = service.accept_request(db, user, thread)
    except service.MessagingError as exc:
        raise _as_http(exc)
    service.mark_read(db, user.id, thread)
    return service.serialize_thread(db, user.id, thread)


@router.post("/threads/{thread_id}/decline", status_code=204)
def decline_request(
    thread_id: uuid.UUID,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    thread = _participant(db, user, thread_id)
    try:
        service.decline_request(db, user.id, thread)
    except service.MessagingError as exc:
        raise _as_http(exc)


@router.post("/threads/{thread_id}/report", status_code=201)
def report_thread(
    thread_id: uuid.UUID,
    payload: schemas.ReportCreate,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    thread = _participant(db, user, thread_id)
    try:
        row = service.report_thread(db, user.id, thread, payload.reason)
    except service.MessagingError as exc:
        raise _as_http(exc)
    return {"id": row.id, "status": row.status}


# -- blocks ---------------------------------------------------------------------


@router.get("/blocks", response_model=list[schemas.BlockPublic])
def list_blocks(
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    return service.list_blocks(db, user.id)


@router.post("/blocks", response_model=schemas.BlockPublic, status_code=201)
def block_user(
    payload: schemas.BlockCreate,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    try:
        return service.block_user(db, user.id, payload.user_id)
    except service.MessagingError as exc:
        raise _as_http(exc)


@router.delete("/blocks/{user_id}", status_code=204)
def unblock_user(
    user_id: uuid.UUID,
    user: CurrentUser = Depends(_messaging_module),
    db: Session = Depends(get_db),
):
    if not service.unblock_user(db, user.id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such block."
        )


# -- public seller profile -----------------------------------------------------------


@router.get("/profiles/{user_id}", response_model=schemas.PublicProfile)
def public_profile(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """The public seller profile — readable signed out (the pool
    links here), so it is gated on the module's global switch
    only, never on a caller. The payload is the profile contract:
    name, member since, area, opt-in phone, reputation summary.
    An unknown or deactivated account is a plain 404."""
    if not module_control.globally_enabled(db, "messaging"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profiles aren't available."
        )
    profile = service.public_profile(db, user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That profile isn't available."
        )
    return profile


# -- moderation queue ------------------------------------------------------------------


@router.get("/mod/reports", response_model=list[schemas.ReportPublic])
def mod_reports(
    status_filter: str = "open",
    _moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    return service.list_reports(db, status_filter)


@router.get("/mod/held", response_model=list[schemas.HeldPublic])
def mod_held(
    _moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    return service.list_held(db)


@router.get("/mod/threads/{thread_id}", response_model=schemas.ModThreadPublic)
def mod_thread(
    thread_id: uuid.UUID,
    _moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.mod_thread_view(db, thread_id)
    except service.MessagingError as exc:
        raise _as_http(exc)


@router.post("/mod/reports/{report_id}/dismiss", response_model=schemas.ReportPublic)
def mod_dismiss_report(
    report_id: uuid.UUID,
    payload: schemas.ReportResolve,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.dismiss_report(db, moderator, report_id, payload.resolution)
    except service.MessagingError as exc:
        raise _as_http(exc)


@router.post("/mod/messages/{message_id}/release", response_model=schemas.HeldPublic)
def mod_release_message(
    message_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.release_message(db, moderator, message_id)
    except service.MessagingError as exc:
        raise _as_http(exc)


@router.post("/mod/messages/{message_id}/discard", response_model=schemas.HeldPublic)
def mod_discard_message(
    message_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.discard_message(db, moderator, message_id)
    except service.MessagingError as exc:
        raise _as_http(exc)


@router.post("/mod/messages/{message_id}/wipe", response_model=schemas.HeldPublic)
def mod_wipe_message(
    message_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.wipe_message(db, moderator, message_id)
    except service.MessagingError as exc:
        raise _as_http(exc)


@router.post("/mod/users/{user_id}/wipe-messages", response_model=schemas.WipeAllResult)
def mod_wipe_all(
    user_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    return service.wipe_all_from_user(db, moderator, user_id)


@router.post("/mod/users/{user_id}/ban", response_model=schemas.BanResult)
def mod_ban_user(
    user_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.ban_user(db, moderator, user_id)
    except service.MessagingError as exc:
        raise _as_http(exc)
