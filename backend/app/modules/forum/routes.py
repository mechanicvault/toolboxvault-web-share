"""Community Forum routes. HTTP layer only — logic lives in
service.py.

Gating, mirroring the marketplace's posture:

- READS are the community's window: categories, thread lists,
  thread views and search answer the identical exact-key payload
  to signed-in users and to logged-out visitors (the /public
  twins). A signed-in caller with a valid token gets their own
  held posts + `mine` flags in the same payloads. Both faces 404
  while the forum kill switch (Admin → Settings → Community) or
  the module's global switch is off.
- WRITES (threads, replies, edits, reports, my-posts) ride the
  forum FEATURE module gate (require_module): switch the module
  off for a group and those answers are 403
  {code: module_unavailable}.
- FAVORITES (list / star / unstar, Wave 3) ride the same module
  gate + the kill switch, but NOT the paid gate — starring is a
  private reading aid, not publishing. The list answers only the
  caller's own rows, each resolved live through its surface's
  visibility rules; invisible targets are silently absent.
- POSTING additionally rides the paid-contribution gate
  (community suite rule): 403 {code: paid_plan_required} while
  enforcement is on and the account doesn't resolve paid.
- The moderation queue rides the community ROLE LADDER
  (user | moderator | community_admin) plus operators — the
  messaging queue's gate, restated here so the forum never
  imports another feature module's routes. HARD thread
  deletion is one rung higher (require_admin: operators +
  community admins, never plain moderators).
- Category furniture is OPERATOR-only (require_operator).
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
    require_operator,
)
from app.core.security import decode_access_token
from app.modules.forum import schemas, service

router = APIRouter()

_forum_module = require_module("forum")

_MODERATOR_ROLES = ("moderator", "community_admin")

_PAID_MESSAGE = (
    "Posting in the forum needs a paid plan. Reading stays free "
    "for everyone — upgrade to join the conversation."
)


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


def require_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """The admin tier's gate — HARD thread deletion lives here
    (owner directive 2026-10-22): operators and community
    admins only. Plain moderators tombstone posts; they never
    erase a whole conversation."""
    if user.is_operator or user.role == "community_admin":
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access only.",
    )


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser | None:
    """The reading face's viewer: a valid bearer token resolves
    the caller (their held posts + mine flags appear); anything
    else — no token, a stale one, a deactivated account — reads
    as anonymous. Reading never 401s."""
    if credentials is None:
        return None
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        return None
    try:
        return get_current_user(user_id, db)
    except HTTPException:
        return None


def _is_mod(user: CurrentUser | None) -> bool:
    return bool(
        user is not None
        and (user.is_operator or user.role in _MODERATOR_ROLES)
    )


def _publish_gate(db: Session, user_id: uuid.UUID) -> None:
    if not service.can_post(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "paid_plan_required", "message": _PAID_MESSAGE},
        )


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.RateLimited):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, service.ForumNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _forum_off() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="The forum isn't available right now.",
    )


def _check_on(db: Session) -> None:
    if not service.forum_enabled(db):
        raise _forum_off()


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "forum", "status": "ok"}


# -- reads (everyone) --------------------------------------------------------------


def _categories(db: Session, viewer: CurrentUser | None) -> list[dict]:
    _check_on(db)
    # The permanent Bug/Feature boards are members-only reading
    # (owner 2026-11-10): an anonymous audience's board rows
    # carry no feedback counts or latest-post data, while the
    # forum's own rooms serialize exactly as they always have.
    return service.list_categories(
        db, viewer_is_mod=_is_mod(viewer), anonymous=viewer is None
    )


@router.get("/categories", response_model=list[schemas.CategoryPublic])
def categories(
    viewer: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    return _categories(db, viewer)


@router.get("/public/categories", response_model=list[schemas.CategoryPublic])
def public_categories(db: Session = Depends(get_db)):
    return _categories(db, None)


def _threads(
    db: Session,
    category_id: uuid.UUID,
    viewer: CurrentUser | None,
    limit: int,
    offset: int,
) -> list[dict]:
    _check_on(db)
    try:
        return service.list_threads(
            db,
            category_id,
            viewer.id if viewer else None,
            viewer_is_mod=_is_mod(viewer),
            limit=limit,
            offset=offset,
        )
    except service.ForumError as exc:
        raise _as_http(exc)


@router.get(
    "/categories/{category_id}/threads",
    response_model=list[schemas.ThreadPublic],
)
def category_threads(
    category_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    viewer: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    return _threads(db, category_id, viewer, limit, offset)


@router.get(
    "/public/categories/{category_id}/threads",
    response_model=list[schemas.ThreadPublic],
)
def public_category_threads(
    category_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return _threads(db, category_id, None, limit, offset)


def _thread(
    db: Session, thread_id: uuid.UUID, viewer: CurrentUser | None
) -> dict:
    _check_on(db)
    try:
        return service.thread_view(
            db,
            thread_id,
            viewer.id if viewer else None,
            viewer_is_mod=_is_mod(viewer),
        )
    except service.ForumError as exc:
        raise _as_http(exc)


@router.get("/threads/{thread_id}", response_model=schemas.ThreadDetailPublic)
def thread(
    thread_id: uuid.UUID,
    viewer: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    return _thread(db, thread_id, viewer)


@router.get(
    "/public/threads/{thread_id}", response_model=schemas.ThreadDetailPublic
)
def public_thread(thread_id: uuid.UUID, db: Session = Depends(get_db)):
    return _thread(db, thread_id, None)


def _search(db: Session, q: str, viewer: CurrentUser | None) -> list[dict]:
    _check_on(db)
    return service.search_threads(
        db, q, viewer.id if viewer else None, viewer_is_mod=_is_mod(viewer)
    )


@router.get("/search", response_model=list[schemas.ThreadPublic])
def search(
    q: str = "",
    viewer: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    return _search(db, q, viewer)


@router.get("/public/search", response_model=list[schemas.ThreadPublic])
def public_search(q: str = "", db: Session = Depends(get_db)):
    return _search(db, q, None)


# -- writes (members) ---------------------------------------------------------------


@router.post(
    "/threads",
    response_model=schemas.ThreadDetailPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_thread(
    payload: schemas.ThreadCreate,
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    _publish_gate(db, user.id)
    try:
        return service.create_thread(
            db,
            user,
            category_id=payload.category_id,
            title=payload.title,
            body=payload.body,
            link_type=payload.link_type,
            link_id=payload.link_id,
        )
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post(
    "/threads/{thread_id}/replies",
    response_model=schemas.PostPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_reply(
    thread_id: uuid.UUID,
    payload: schemas.ReplyCreate,
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    _publish_gate(db, user.id)
    try:
        return service.create_reply(
            db,
            user,
            thread_id=thread_id,
            body=payload.body,
            quote_post_id=payload.quote_post_id,
            link_type=payload.link_type,
            link_id=payload.link_id,
        )
    except service.ForumError as exc:
        raise _as_http(exc)


@router.put("/posts/{post_id}", response_model=schemas.PostPublic)
def edit_post(
    post_id: uuid.UUID,
    payload: schemas.PostEdit,
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    _publish_gate(db, user.id)
    try:
        return service.edit_post(db, user, post_id=post_id, body=payload.body)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.delete("/posts/{post_id}", response_model=schemas.PostPublic)
def delete_post(
    post_id: uuid.UUID,
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        return service.delete_post(db, user, post_id=post_id)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post(
    "/posts/{post_id}/report",
    response_model=schemas.ReportPublic,
    status_code=status.HTTP_201_CREATED,
)
def report_post(
    post_id: uuid.UUID,
    payload: schemas.ReportCreate,
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        return service.report_post(
            db, user, post_id=post_id, reason=payload.reason
        )
    except service.ForumError as exc:
        raise _as_http(exc)


@router.get("/favorites", response_model=list[schemas.FavoritePublic])
def my_favorites(
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    """The member's own favorites, resolved live (invisible
    targets silently absent). Private by construction — the
    route answers only the caller's rows."""
    _check_on(db)
    return service.list_favorites(db, user.id, viewer_is_mod=_is_mod(user))


@router.post(
    "/favorites",
    response_model=schemas.FavoritePublic,
    status_code=status.HTTP_201_CREATED,
)
def star_favorite(
    payload: schemas.FavoriteCreate,
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    """Star a thread or a permanent board's post. A private
    reading aid, not publishing — no paid gate; the forum
    module gate above is the only lock. The target must be
    visible to the caller right now (404 otherwise)."""
    _check_on(db)
    try:
        return service.star_favorite(
            db,
            user.id,
            kind=payload.kind,
            target_id=payload.target_id,
            viewer_is_mod=_is_mod(user),
        )
    except service.ForumError as exc:
        raise _as_http(exc)


@router.delete(
    "/favorites/{kind}/{target_id}", status_code=status.HTTP_204_NO_CONTENT
)
def unstar_favorite(
    kind: str,
    target_id: uuid.UUID,
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    try:
        service.unstar_favorite(db, user.id, kind=kind, target_id=target_id)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.get("/mine/posts", response_model=list[schemas.PostPublic])
def my_posts(
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    return service.my_posts(db, user.id)


@router.get("/mine/threads", response_model=list[schemas.ThreadPublic])
def my_threads(
    user: CurrentUser = Depends(_forum_module),
    db: Session = Depends(get_db),
):
    _check_on(db)
    return service.my_threads(db, user.id)


# -- moderation queue ---------------------------------------------------------------


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


# -- community blocks (admin lane, owner ruling 2026-11-06) ----------
# The queue READS ride the moderator ladder (the queue shows
# who is blocked); imposing and lifting ride the block gate —
# god + moderator_admin only, enforced here AND in the service
# (forum.blocks.require_block_admin), so no future caller can
# widen it by accident. my-blocks is any signed-in member
# reading their own standing (the blocked-user banner's feed).


def _block_as_http(exc: Exception) -> HTTPException:
    from app.modules.forum import blocks as community_blocks

    if isinstance(exc, community_blocks.BlockNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


@router.get("/mod/blocks", response_model=list[schemas.BlockPublic])
def mod_blocks(
    active_only: bool = True,
    _moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    from app.modules.forum import blocks as community_blocks

    return community_blocks.list_blocks(db, active_only=active_only)


@router.post("/mod/blocks", response_model=schemas.BlockPublic)
def mod_create_block(
    payload: schemas.BlockCreate,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.modules.forum import blocks as community_blocks

    try:
        return community_blocks.block_user(
            db,
            admin,
            user_id=payload.user_id,
            account_number=payload.account_number,
            feature=payload.feature,
            reason=payload.reason,
        )
    except community_blocks.BlockError as exc:
        raise _block_as_http(exc)


@router.post("/mod/blocks/{block_id}/lift", response_model=schemas.BlockPublic)
def mod_lift_block(
    block_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.modules.forum import blocks as community_blocks

    try:
        return community_blocks.lift_block(db, admin, block_id)
    except community_blocks.BlockError as exc:
        raise _block_as_http(exc)


@router.get("/mod/my-blocks", response_model=list[schemas.BlockPublic])
def my_blocks(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.forum import blocks as community_blocks

    return community_blocks.my_blocks(db, user.id)


@router.get("/mod/threads/{thread_id}", response_model=schemas.ThreadDetailPublic)
def mod_thread(
    thread_id: uuid.UUID,
    _moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.mod_thread_view(db, thread_id)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post(
    "/mod/reports/{report_id}/dismiss", response_model=schemas.ReportPublic
)
def mod_dismiss_report(
    report_id: uuid.UUID,
    payload: schemas.ReportResolve,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.dismiss_report(db, moderator, report_id, payload.resolution)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post("/mod/posts/{post_id}/release", response_model=schemas.HeldPublic)
def mod_release_post(
    post_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.release_post(db, moderator, post_id)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post("/mod/posts/{post_id}/discard", response_model=schemas.HeldPublic)
def mod_discard_post(
    post_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.discard_post(db, moderator, post_id)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post("/mod/posts/{post_id}/remove", response_model=schemas.PostPublic)
def mod_remove_post(
    post_id: uuid.UUID,
    payload: schemas.ReportResolve,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.remove_post(db, moderator, post_id, payload.resolution)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post(
    "/mod/threads/{thread_id}/pin", response_model=schemas.ThreadPublic
)
def mod_pin_thread(
    thread_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.set_thread_pinned(db, moderator, thread_id, True)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post(
    "/mod/threads/{thread_id}/unpin", response_model=schemas.ThreadPublic
)
def mod_unpin_thread(
    thread_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.set_thread_pinned(db, moderator, thread_id, False)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post(
    "/mod/threads/{thread_id}/lock", response_model=schemas.ThreadPublic
)
def mod_lock_thread(
    thread_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.set_thread_locked(db, moderator, thread_id, True)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post(
    "/mod/threads/{thread_id}/unlock", response_model=schemas.ThreadPublic
)
def mod_unlock_thread(
    thread_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.set_thread_locked(db, moderator, thread_id, False)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.delete(
    "/mod/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT
)
def mod_delete_thread(
    thread_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin-tier HARD delete (operators + community admins):
    the thread, all its posts and every report on them go for
    good. See service.delete_thread for the cascade contract."""
    try:
        service.delete_thread(db, admin, thread_id)
    except service.ForumError as exc:
        raise _as_http(exc)


@router.post(
    "/mod/users/{user_id}/wipe-posts", response_model=schemas.WipeResult
)
def mod_wipe_posts(
    user_id: uuid.UUID,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.wipe_posts_from_user(db, moderator, user_id)
    except service.ForumError as exc:
        raise _as_http(exc)


# -- operator category furniture ------------------------------------------------------


@router.get("/admin/categories", response_model=list[schemas.CategoryPublic])
def admin_categories(
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return service.list_all_categories(db)


@router.post(
    "/admin/categories",
    response_model=schemas.CategoryPublic,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_category(
    payload: schemas.CategoryCreate,
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        return service.create_category(
            db,
            name=payload.name,
            description=payload.description,
            sort_order=payload.sort_order,
        )
    except service.ForumError as exc:
        raise _as_http(exc)


@router.put(
    "/admin/categories/{category_id}", response_model=schemas.CategoryPublic
)
def admin_update_category(
    category_id: uuid.UUID,
    payload: schemas.CategoryUpdate,
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        return service.update_category(
            db,
            category_id,
            name=payload.name,
            description=payload.description,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
    except service.ForumError as exc:
        raise _as_http(exc)
