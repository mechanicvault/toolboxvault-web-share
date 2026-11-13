"""3D print files routes. HTTP layer only — logic lives in
service.py.

Gating, mirroring the forum's posture:

- READS are the public's window: browse, search, file pages,
  preview images and PRINT downloads answer signed-in users
  and logged-out visitors identically. The whole surface 404s
  while the prints module is off for the public
  (module_control.usable_anywhere — global switch, group
  assignment, normal tier).
- WRITES (upload, update, rate, comment, flag, maker links)
  ride the prints FEATURE module gate (require_module):
  switch the module off for a group and those answers are 403
  {code: module_unavailable}. Upload + comment writes also
  ride the community-block check (a member blocked from the
  print files by an admin can't publish there — the forum's
  blocks machinery, feature key "print_files").
- STEP downloads are registered-only (owner order): the door
  itself requires a session — a signed-out request is a 401,
  the site's standard sign-in refusal.
- The MODERATION queue rides the community role ladder
  (moderator | community_admin | operator), like the forum's;
  REMOVING another member's file or comment is one rung
  higher — god / moderator_admin tiers and operators only
  (owner order: "moderator admins or god" remove any file).
"""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import (
    CurrentUser,
    _bearer,
    get_current_user,
    require_module,
)
from app.core.security import create_visitor_token, decode_access_token
from app.modules.core import module_control, teaser, tiers, visitor_preview
from app.modules.forum import blocks as community_blocks
from app.modules.prints import categories, schemas, service

router = APIRouter()

_prints_module = require_module("prints")

_MODERATOR_ROLES = ("moderator", "community_admin")


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser | None:
    """The reading face's viewer (the forum's exact pattern):
    a valid bearer <redacted> resolves the caller; anything else
    reads as anonymous. Reading never 401s."""
    if credentials is None:
        return None
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        return None
    try:
        return get_current_user(user_id, db)
    except HTTPException:
        return None


def _require_open(db: Session) -> None:
    """Reads 404 while the module is off for the public (the
    forum's kill-switch posture, read through the public lens)."""
    if not module_control.usable_anywhere(db, "prints"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That print file isn't available.",
        )


def _require_preview_owner(viewer, row) -> None:
    """The "View as visitor" preview's gate (Sweep D5): the
    preview fetch is the PUBLISHER's alone — anyone else
    already reads the visitor shape (or, signed out, the
    public one), so a preview request from a non-owner is a
    403, never a silent downgrade of their own view."""
    if viewer is None or viewer.id != row.publisher_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the publisher can preview this listing as a visitor.",
        )


def require_moderator(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """The moderation queue's gate (the forum's, restated):
    role-ladder moderators and community admins, plus
    operators."""
    if user.is_operator or user.role in _MODERATOR_ROLES:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Moderator access only.",
    )


def _require_remover(user: CurrentUser) -> CurrentUser:
    """Removing ANOTHER member's content: god / moderator_admin
    tiers and operators (owner order). Plain moderators work
    the queue — dismiss flags, read everything — but the
    removal of someone else's file is an admin act."""
    if user.is_operator or tiers.resolved_tier(user) in ("god", "moderator_admin"):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Removing another member's file is reserved to the site admins.",
    )


def _not_blocked(db: Session, user: CurrentUser) -> None:
    try:
        community_blocks.require_not_blocked(db, user.id, "print_files")
    except community_blocks.BlockError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc


def _as_http(exc: service.PrintsError) -> HTTPException:
    if isinstance(exc, service.PrintsNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


async def _read_upload(
    upload: UploadFile | None, cap: int
) -> tuple[str, bytes] | None:
    """Read an uploaded part with its cap (the vCard imports'
    read-cap-plus-one pattern, sized for print files)."""
    if upload is None:
        return None
    data = await upload.read(cap + 1)
    if len(data) > cap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That file is too large.",
        )
    return (upload.filename or "", data)


# -- public reads -------------------------------------------------------


@router.post("/visit", response_model=schemas.VisitCountView)
def record_visit(request: Request, response: Response, db: Session = Depends(get_db)):
    """The 3D Print Files page's unique-visitor counter (owner
    order, 2026-11-10): the teaser/Downloads counter, mirrored —
    the page calls this once on load and renders the returned
    count as bare digits at its foot. The counting rules (its
    own counted cookie, the same automation and operator-IP
    exclusions, its own row in the counter table) live in
    core/teaser.py; here we only mint the counted cookie when
    the service says this browser was just counted, and hold
    the shelf's read posture: while the prints module is off
    for the public the visit 404s with the reads. No auth: the
    count is public by design, and the response carries
    nothing but the number."""
    _require_open(db)
    count, counted = teaser.record_prints_visit(db, request)
    if counted:
        response.set_cookie(
            teaser.PRINTS_COUNT_COOKIE,
            create_visitor_token(),
            max_age=teaser.COUNT_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.app_base_url.startswith("https://"),
            path="/",
        )
    return {"count": count}


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    _require_open(db)
    return {"categories": list(categories.CATEGORIES)}


@router.get("/files")
def browse_files(
    q: str = "",
    category: str | None = None,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
    viewer: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    _require_open(db)
    if category is not None and not categories.is_category(category):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That isn't one of the shelf's categories.",
        )
    if sort not in service.SORTS:
        sort = "newest"
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    files, total = service.browse(
        db, q=q, category=category, sort=sort, limit=limit, offset=offset, viewer=viewer
    )
    return {"files": files, "total": total, "stats": service.shelf_stats(db)}


@router.get("/files/{file_id}")
def file_detail(
    file_id: uuid.UUID,
    as_visitor: bool = Query(default=False),
    viewer: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    _require_open(db)
    try:
        row = service.get_live_file(db, file_id)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
    if as_visitor:
        # "View as visitor" (Sweep D5): the publisher's preview
        # fetch — the SAME detail serializer, shaped by the
        # visitor stand-in (a signed-in member with no
        # relationship to the listing), so the preview is the
        # real non-owner data shape, not owner data with the
        # furniture hidden. A plain read: opening a listing
        # counts nothing for any viewer, and neither does this.
        _require_preview_owner(viewer, row)
        return service.detail(db, row, visitor_preview.visitor_viewer())
    return service.detail(db, row, viewer)


@router.get("/files/{file_id}/comments")
def file_comments(
    file_id: uuid.UUID,
    as_visitor: bool = Query(default=False),
    viewer: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    _require_open(db)
    try:
        row = service.get_live_file(db, file_id)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
    if as_visitor:
        _require_preview_owner(viewer, row)
        return {
            "comments": service.list_comments(
                db, file_id, visitor_preview.visitor_viewer()
            )
        }
    try:
        return {"comments": service.list_comments(db, file_id, viewer)}
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.get("/files/{file_id}/preview")
def file_preview(
    file_id: uuid.UUID, size: str = "card", db: Session = Depends(get_db)
):
    """The listing's cover image. Serves the right-sized
    rendition, never the multi-MB original: `size=card` (the
    default — the browse cards and the record header plate)
    or `size=display` (the cover's big-preview modal). A
    listing whose photo can't be rendered falls back to its
    original bytes — never a broken image."""
    _require_open(db)
    row = service.get_file(db, file_id)
    if row is None or row.status != "live" or row.preview_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That print file isn't available.",
        )
    if size not in service.PREVIEW_SIZES:
        size = "card"
    try:
        data, content_type = service.preview_bytes(row, size)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
    return Response(content=data, media_type=content_type)


@router.get("/files/{file_id}/media/{media_id}")
def media_bytes(
    file_id: uuid.UUID,
    media_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """One showcase item's bytes — public like the rest of
    the listing (the Photos / Video tab and its viewer read
    here). Single-range requests are honored: a video player
    asks for ranges to start and seek, where the plain full
    serve the other doors use would stall it."""
    _require_open(db)
    row = service.get_file(db, file_id)
    media = (
        service.get_media(db, file_id, media_id) if row is not None else None
    )
    if row is None or row.status != "live" or media is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That media isn't available.",
        )
    if media.kind == "photo":
        # A photo serves its bounded display rendition (the
        # gallery tiles and the viewer read here) — never the
        # multi-MB original, and the original when no
        # rendition can be made. Range requests are a video
        # concern; a photo answers whole.
        try:
            data, content_type = service.media_photo_bytes(media)
        except service.PrintsError as exc:
            raise _as_http(exc) from exc
        return Response(content=data, media_type=content_type)
    try:
        data = service.fetch_bytes(media.storage_key)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
    total = len(data)
    range_header = request.headers.get("range", "")
    if range_header.startswith("bytes=") and "," not in range_header:
        start_s, _, end_s = range_header[len("bytes=") :].partition("-")
        try:
            if start_s == "":
                # Suffix range: the last N bytes.
                suffix = int(end_s)
                start, end = max(0, total - suffix), total - 1
            else:
                start = int(start_s)
                end = int(end_s) if end_s else total - 1
        except ValueError:
            start, end = -1, -1
        if start < 0 or start >= total:
            return Response(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{total}"},
            )
        end = min(end, total - 1)
        return Response(
            content=data[start : end + 1],
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=media.content_type or "application/octet-stream",
            headers={
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Accept-Ranges": "bytes",
            },
        )
    return Response(
        content=data,
        media_type=media.content_type or "application/octet-stream",
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/files/{file_id}/download")
def download_print(
    file_id: uuid.UUID,
    version: int | None = None,
    db: Session = Depends(get_db),
):
    """The public print download — counted first, then served
    (the Part 1 discipline), for everyone, signed in or not."""
    _require_open(db)
    found = service.record_print_download(db, file_id, version)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That print file isn't available.",
        )
    _row, version_row = found
    try:
        data = service.fetch_bytes(version_row.print_key)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{version_row.print_filename}"'
        },
    )


# -- registered writes ----------------------------------------------------


@router.get("/files/{file_id}/step")
def download_step(
    file_id: uuid.UUID,
    version: int | None = None,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    """STEP downloads are registered-only (owner order): this
    door rides the session + module gate, unlike the print
    download above."""
    found = service.record_step_download(db, file_id, version)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That version has no STEP file.",
        )
    _row, version_row = found
    try:
        data = service.fetch_bytes(version_row.step_key)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{version_row.step_filename}"'
        },
    )


@router.post("/files", status_code=status.HTTP_201_CREATED)
async def publish_file(
    title: str = Form(...),
    description: str = Form(""),
    category: str = Form(...),
    note: str = Form(""),
    print_file: UploadFile = File(...),
    step_file: UploadFile | None = File(None),
    preview: UploadFile | None = File(None),
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    _not_blocked(db, user)
    print_upload = await _read_upload(print_file, service.PRINT_MAX_BYTES)
    step_upload = await _read_upload(step_file, service.STEP_MAX_BYTES)
    photo_upload = await _read_upload(preview, service.PHOTO_MAX_BYTES)
    try:
        return service.create_file(
            db,
            user,
            title=title,
            description=description,
            category_key=category,
            note=note,
            print_upload=print_upload,
            step_upload=step_upload,
            photo_upload=photo_upload,
        )
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.post("/files/{file_id}/versions", status_code=status.HTTP_201_CREATED)
async def publish_update(
    file_id: uuid.UUID,
    note: str = Form(""),
    print_file: UploadFile = File(...),
    step_file: UploadFile | None = File(None),
    preview: UploadFile | None = File(None),
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    _not_blocked(db, user)
    print_upload = await _read_upload(print_file, service.PRINT_MAX_BYTES)
    step_upload = await _read_upload(step_file, service.STEP_MAX_BYTES)
    photo_upload = await _read_upload(preview, service.PHOTO_MAX_BYTES)
    try:
        return service.add_version(
            db,
            user,
            file_id,
            note=note,
            print_upload=print_upload,
            step_upload=step_upload,
            photo_upload=photo_upload,
        )
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.put("/files/{file_id}")
def edit_listing(
    file_id: uuid.UUID,
    body: schemas.ListingEditRequest,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    """The publisher edits their LISTING (title, description,
    category — Ryan: 'edit your entry to update photos and
    text etc'). Publisher-only in the service; a listing edit
    never moves the file's version."""
    _not_blocked(db, user)
    try:
        return service.update_listing(
            db,
            user,
            file_id,
            title=body.title,
            description=body.description,
            category_key=body.category,
        )
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.post("/files/{file_id}/media/photos")
async def add_media_photo(
    file_id: uuid.UUID,
    photo: UploadFile = File(...),
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    _not_blocked(db, user)
    upload = await _read_upload(photo, service.PHOTO_MAX_BYTES)
    try:
        return {"media": service.add_photo(db, user, file_id, upload)}
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.post("/files/{file_id}/media/video")
async def add_media_video(
    file_id: uuid.UUID,
    video: UploadFile = File(...),
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    """The listing's one video. The 30-second cap is verified
    on the server from the container's own duration — see
    service.validate_video_upload."""
    _not_blocked(db, user)
    upload = await _read_upload(video, service.VIDEO_MAX_BYTES)
    try:
        return {"media": service.add_video(db, user, file_id, upload)}
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.delete("/files/{file_id}/media/{media_id}")
def remove_media_item(
    file_id: uuid.UUID,
    media_id: uuid.UUID,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    _not_blocked(db, user)
    try:
        return {"media": service.remove_media(db, user, file_id, media_id)}
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.put("/files/{file_id}/media/order")
def reorder_media_items(
    file_id: uuid.UUID,
    body: schemas.MediaOrderRequest,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    _not_blocked(db, user)
    try:
        return {"media": service.reorder_media(db, user, file_id, body.media_ids)}
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.delete("/files/{file_id}")
def remove_own_file(
    file_id: uuid.UUID,
    body: schemas.RemoveRequest | None = None,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    try:
        return service.remove_file(
            db, user, file_id, reason=(body.reason if body else "")
        )
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.post("/files/{file_id}/rate")
def rate_file(
    file_id: uuid.UUID,
    body: schemas.RateRequest,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    try:
        return service.rate_file(db, user, file_id, body.stars)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.get("/files/{file_id}/follow", response_model=schemas.FollowView)
def get_follow(
    file_id: uuid.UUID,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    """My per-file update opt-in state for this listing
    (sweep E4; the listing page's toggle reads it, and the
    detail payload carries the same flag as `following`)."""
    try:
        service.get_live_file(db, file_id)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
    return schemas.FollowView(following=service.is_following(db, file_id, user))


@router.put("/files/{file_id}/follow", response_model=schemas.FollowView)
def put_follow(
    file_id: uuid.UUID,
    body: schemas.FollowRequest,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    """Flip my per-file update opt-in in place (sweep E4)."""
    try:
        following = service.set_following(db, user, file_id, body.following)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
    return schemas.FollowView(following=following)


@router.post("/files/{file_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(
    file_id: uuid.UUID,
    body: schemas.CommentRequest,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    _not_blocked(db, user)
    try:
        return service.add_comment(db, user, file_id, body.body)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.delete("/comments/{comment_id}")
def remove_own_comment(
    comment_id: uuid.UUID,
    body: schemas.RemoveRequest | None = None,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    try:
        return service.remove_comment(
            db, user, comment_id, reason=(body.reason if body else "")
        )
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.post("/files/{file_id}/report", status_code=status.HTTP_201_CREATED)
def report_file(
    file_id: uuid.UUID,
    body: schemas.ReportRequest,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    try:
        return service.report_file(db, user, file_id, body.reason)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.post("/comments/{comment_id}/report", status_code=status.HTTP_201_CREATED)
def report_comment(
    comment_id: uuid.UUID,
    body: schemas.ReportRequest,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    try:
        return service.report_comment(db, user, comment_id, body.reason)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


# -- maker profile links + my files ---------------------------------------


@router.get("/me/files")
def my_files(
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    return {"files": service.my_files(db, user)}


@router.get("/me/links")
def my_links(
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    return {"links": [service.link_view(r) for r in service.list_links(db, user.id)]}


@router.post("/me/links", status_code=status.HTTP_201_CREATED)
def create_link(
    body: schemas.LinkRequest,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    try:
        return service.create_link(db, user, label=body.label, url=body.url)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.put("/me/links/{link_id}")
def update_link(
    link_id: uuid.UUID,
    body: schemas.LinkRequest,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    try:
        return service.update_link(db, user, link_id, label=body.label, url=body.url)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.delete("/me/links/{link_id}")
def delete_link(
    link_id: uuid.UUID,
    user: CurrentUser = Depends(_prints_module),
    db: Session = Depends(get_db),
):
    try:
        service.delete_link(db, user, link_id)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
    return {"ok": True}


# -- moderation queue ------------------------------------------------------


@router.get("/moderation/reports")
def moderation_reports(
    status_filter: str = "open",
    _user: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    return {"reports": service.list_reports(db, status_filter)}


@router.post("/moderation/reports/{report_id}/dismiss")
def dismiss_report(
    report_id: uuid.UUID,
    body: schemas.DismissRequest,
    user: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return service.dismiss_report(db, user, report_id, body.resolution)
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.post("/moderation/files/{file_id}/remove")
def moderation_remove_file(
    file_id: uuid.UUID,
    body: schemas.RemoveRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_remover(user)
    try:
        return service.remove_file(
            db, user, file_id, reason=body.reason, by_moderator=True
        )
    except service.PrintsError as exc:
        raise _as_http(exc) from exc


@router.post("/moderation/comments/{comment_id}/remove")
def moderation_remove_comment(
    comment_id: uuid.UUID,
    body: schemas.RemoveRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_remover(user)
    try:
        return service.remove_comment(
            db, user, comment_id, reason=body.reason, by_moderator=True
        )
    except service.PrintsError as exc:
        raise _as_http(exc) from exc
