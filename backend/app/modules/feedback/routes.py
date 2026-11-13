"""Feedback boards routes. HTTP layer only — logic lives in
service.py.

Gating:

- READS are members-only (owner 2026-11-10, busy work #1 —
  supersedes the 2026-10-20 public-reading ruling): the board
  lists and post views refuse anonymous callers with a 401 on
  BOTH faces. The /public twins keep their routes (old links
  and snapshots resolve to a real door, never a bare 404) but
  answer the identical gate — no anonymous payload exists
  anymore. Any registered account reads: normal, free, and
  the downloads level included. A valid bearer <redacted> also
  adds the caller's held posts + `mine` / `voted_by_me` flags.
  Both faces 404 for members while the module's global switch
  is off; the auth gate runs first, so a signed-out caller
  learns nothing about the module's state.
- WRITES (post, vote, comment, report, my-posts) ride the
  feedback FEATURE module gate — but NOT the forum's paid gate:
  any signed-in account may contribute, free included (Ryan's
  ruling: open feedback). The spam firewall still screens
  every body and its trust budgets still brake volume.
- Status changes + the moderation queue ride the community
  ROLE LADDER (moderator | community_admin) plus operators —
  the forum/messaging gate, restated here so this module never
  imports another feature module's routes.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import (
    CurrentUser,
    _bearer,
    get_current_user,
    require_module,
)
from app.core.security import decode_access_token
from app.modules.core import module_control
from app.modules.feedback import schemas, service

router = APIRouter()

_feedback_module = require_module("feedback")

_MODERATOR_ROLES = ("moderator", "community_admin")


def require_moderator(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.is_operator or user.role in _MODERATOR_ROLES:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Moderator access only.",
    )


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser | None:
    """Resolve a bearer <redacted> when one is offered (the
    forum's twin): a valid token resolves the caller; anything
    else resolves to None."""
    if credentials is None:
        return None
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        return None
    try:
        return get_current_user(user_id, db)
    except HTTPException:
        return None


def require_reader(
    viewer: CurrentUser | None = Depends(get_optional_user),
) -> CurrentUser:
    """The boards' reading gate (owner 2026-11-10): a valid
    session or a 401 — the same refusal the write faces give an
    anonymous caller. Registration is the whole bar: no module
    reach, tier, or role is asked beyond it, so every member
    (downloads level included) reads exactly as before, and
    the board assistant's own account — a plain member seat —
    keeps reading with its login."""
    if viewer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return viewer


def _is_mod(user: CurrentUser | None) -> bool:
    return bool(
        user is not None and (user.is_operator or user.role in _MODERATOR_ROLES)
    )


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.RateLimited):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, service.FeedbackNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _check_on(db: Session) -> None:
    if not module_control.globally_enabled(db, "feedback"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback isn't available right now.",
        )


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "feedback", "status": "ok"}


# -- reads (registered members only — owner 2026-11-10) ------------------------------


def _list(
    db: Session,
    viewer: CurrentUser,
    board: str,
    status_filter: str,
    sort: str = "new",
):
    _check_on(db)
    return service.list_posts(
        db,
        board=board,
        viewer_id=viewer.id if viewer else None,
        viewer_is_mod=_is_mod(viewer),
        status_filter=status_filter,
        sort=sort,
    )


@router.get("/boards/{board}", response_model=list[schemas.PostPublic])
def board_posts(
    board: str,
    status_filter: str = "",
    sort: str = "new",
    viewer: CurrentUser = Depends(require_reader),
    db: Session = Depends(get_db),
):
    try:
        return _list(db, viewer, board, status_filter, sort)
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.get("/public/boards/{board}", response_model=list[schemas.PostPublic])
def public_board_posts(
    board: str,
    status_filter: str = "",
    sort: str = "new",
    viewer: CurrentUser = Depends(require_reader),
    db: Session = Depends(get_db),
):
    try:
        return _list(db, viewer, board, status_filter, sort)
    except service.FeedbackError as exc:
        raise _as_http(exc)


def _detail(db: Session, viewer: CurrentUser, post_id: uuid.UUID):
    _check_on(db)
    return service.post_detail(
        db,
        post_id,
        viewer_id=viewer.id if viewer else None,
        viewer_is_mod=_is_mod(viewer),
    )


@router.get("/posts/{post_id}", response_model=schemas.PostDetailPublic)
def post_detail(
    post_id: uuid.UUID,
    viewer: CurrentUser = Depends(require_reader),
    db: Session = Depends(get_db),
):
    try:
        return _detail(db, viewer, post_id)
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.get("/public/posts/{post_id}", response_model=schemas.PostDetailPublic)
def public_post_detail(
    post_id: uuid.UUID,
    viewer: CurrentUser = Depends(require_reader),
    db: Session = Depends(get_db),
):
    try:
        return _detail(db, viewer, post_id)
    except service.FeedbackError as exc:
        raise _as_http(exc)


# -- writes (any signed-in account — the deliberate deviation) -----------------------


@router.post(
    "/posts",
    response_model=schemas.PostPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_post(
    payload: schemas.PostWrite,
    user: CurrentUser = Depends(_feedback_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        return service.create_post(
            db,
            user,
            board=payload.board,
            title=payload.title,
            body=payload.body,
            urgency=payload.urgency,
        )
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.post("/posts/{post_id}/vote", response_model=schemas.PostPublic)
def toggle_vote(
    post_id: uuid.UUID,
    user: CurrentUser = Depends(_feedback_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        return service.toggle_vote(db, user, post_id)
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.post(
    "/posts/{post_id}/comments",
    response_model=schemas.CommentPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    post_id: uuid.UUID,
    payload: schemas.CommentWrite,
    user: CurrentUser = Depends(_feedback_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        return service.create_comment(db, user, post_id=post_id, body=payload.body)
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.delete("/posts/{post_id}", response_model=schemas.PostPublic)
def delete_post(
    post_id: uuid.UUID,
    user: CurrentUser = Depends(_feedback_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        return service.delete_post(db, user, post_id)
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.delete("/comments/{comment_id}", response_model=schemas.CommentPublic)
def delete_comment(
    comment_id: uuid.UUID,
    user: CurrentUser = Depends(_feedback_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        return service.delete_comment(db, user, comment_id)
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.get("/mine", response_model=list[schemas.PostPublic])
def my_posts(
    board: str = "",
    sort: str = "new",
    user: CurrentUser = Depends(_feedback_module),
    db: Session = Depends(get_db),
):
    """My posts across both boards (or one, with ?board=)."""
    _check_on(db)
    boards = [board] if board else ["bug", "feature"]
    out: list[dict] = []
    try:
        for name in boards:
            out.extend(
                service.list_posts(
                    db,
                    board=name,
                    viewer_id=user.id,
                    viewer_is_mod=_is_mod(user),
                    mine_only=True,
                    sort=sort,
                    limit=500,
                )
            )
    except service.FeedbackError as exc:
        raise _as_http(exc)
    if sort == "top":
        out.sort(key=lambda p: p["vote_count"], reverse=True)
    else:
        out.sort(key=lambda p: p["created_at"], reverse=True)
    return out


@router.post(
    "/reports",
    response_model=schemas.ReportPublic,
    status_code=status.HTTP_201_CREATED,
)
def report(
    payload: schemas.ReportWrite,
    user: CurrentUser = Depends(_feedback_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        return service.report_target(
            db,
            user,
            target_kind=payload.target_kind,
            target_id=payload.target_id,
            reason=payload.reason,
        )
    except service.FeedbackError as exc:
        raise _as_http(exc)


# -- status + moderation queue ----------------------------------------------------------


@router.post("/posts/{post_id}/urgency", response_model=schemas.PostPublic)
def set_urgency(
    post_id: uuid.UUID,
    payload: schemas.UrgencyWrite,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    """The moderator urgency lever. The filer has NO route
    here — their picker locked at submission (owner
    2026-11-06) — so a member token gets a 403, not an edit
    box that refuses later."""
    _check_on(db)
    try:
        return service.set_urgency(
            db, moderator, post_id, urgency=payload.urgency
        )
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.post("/posts/{post_id}/status", response_model=schemas.PostPublic)
def set_status(
    post_id: uuid.UUID,
    payload: schemas.StatusWrite,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        return service.set_status(
            db, moderator, post_id, status=payload.status, note=payload.note
        )
    except service.FeedbackError as exc:
        raise _as_http(exc)


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


@router.post("/mod/reports/{report_id}/dismiss", response_model=schemas.ReportPublic)
def mod_dismiss_report(
    report_id: uuid.UUID,
    payload: schemas.DismissWrite,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.dismiss_report(db, moderator, report_id, payload.note)
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.post("/mod/targets/{target_kind}/{target_id}/release", response_model=schemas.HeldPublic)
def mod_release(
    target_kind: str,
    target_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.release_target(db, moderator, target_kind, target_id)
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.post("/mod/targets/{target_kind}/{target_id}/discard", response_model=schemas.HeldPublic)
def mod_discard(
    target_kind: str,
    target_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.discard_target(db, moderator, target_kind, target_id)
    except service.FeedbackError as exc:
        raise _as_http(exc)


@router.post("/mod/targets/{target_kind}/{target_id}/remove", response_model=schemas.HeldPublic)
def mod_remove(
    target_kind: str,
    target_id: uuid.UUID,
    payload: schemas.RemoveWrite,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.remove_target(
            db, moderator, target_kind, target_id, payload.reason
        )
    except service.FeedbackError as exc:
        raise _as_http(exc)
