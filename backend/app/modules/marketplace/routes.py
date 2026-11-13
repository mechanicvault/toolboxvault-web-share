"""Tools For Sale routes. HTTP layer only — logic lives in
service.py (listings) and reputation.py (the ratings engine).

Gating, mirroring the Community Parts pool's posture exactly:

- OWNER surfaces (my listings, lifecycle, uploads, my deals) ride
  the marketplace FEATURE module gate (require_module): switch
  the module off for a group and those answers are 403
  {code: module_unavailable}.
- The BOARD is the community's window: readable by every
  signed-in user regardless of group and by logged-out visitors
  through the /public twin — both answer the identical exact-key
  payload and both 404 while the marketplace kill switch (Admin
  → Settings → Community & spam) or the module's global switch
  is off.
- The PUBLISH GATE (paid contribution, community suite rule)
  refuses creates, edits of active listings, and reactivations
  for a non-paid account while enforcement is on — 403
  {code: paid_plan_required}, the pool's doorway shape.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, require_module
from app.modules.core import service as core_service
from app.modules.marketplace import attachments, reputation, schemas, service

router = APIRouter()

_marketplace_module = require_module("marketplace")

_PAID_MESSAGE = (
    "Listing on Tools For Sale needs a paid plan. Browsing and "
    "buying stay free — upgrade to post listings."
)


def _publish_gate(db: Session, user_id: uuid.UUID) -> None:
    if not service.can_publish(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "paid_plan_required", "message": _PAID_MESSAGE},
        )


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(
        exc, (service.MarketplaceNotFound, reputation.ReputationNotFound)
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _board_off() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Tools For Sale isn't available right now.",
    )


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "marketplace", "status": "ok"}


@router.get("/stats", response_model=schemas.MarketplaceStats)
def marketplace_stats(
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    """The Active listings panel stat: my listings live on the board."""
    return service.stats(db, user.id)


# -- the board (everyone) ---------------------------------------------------------


def _board(
    db: Session,
    q: str | None,
    listing_type: str | None,
    price_min: float | None,
    price_max: float | None,
    area: str | None,
    seller_id: uuid.UUID | None,
    sort: str,
    limit: int,
    offset: int,
) -> list[dict]:
    if not service.marketplace_enabled(db):
        raise _board_off()
    return service.search_listings(
        db,
        q=q,
        listing_type=listing_type,
        price_min=price_min,
        price_max=price_max,
        area=area,
        seller_id=seller_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/board", response_model=list[schemas.ListingPublic])
def board(
    q: str | None = None,
    listing_type: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    area: str | None = None,
    seller_id: uuid.UUID | None = None,
    sort: str = "newest",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """The board for signed-in users — deliberately NOT behind
    the marketplace module gate: every group browses, including
    accounts the posting side isn't assigned to."""
    return _board(db, q, listing_type, price_min, price_max, area, seller_id, sort, limit, offset)


@router.get("/public/board", response_model=list[schemas.ListingPublic])
def public_board(
    q: str | None = None,
    listing_type: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    area: str | None = None,
    seller_id: uuid.UUID | None = None,
    sort: str = "newest",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """The logged-out window onto the same board: the identical
    exact-key payload, nothing else. Contact actions do not
    exist here — messaging requires an account."""
    return _board(db, q, listing_type, price_min, price_max, area, seller_id, sort, limit, offset)


def _board_one(db: Session, listing_id: uuid.UUID) -> dict:
    if not service.marketplace_enabled(db):
        raise _board_off()
    listing = service.get_public_listing(db, listing_id)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That listing isn't available.",
        )
    seller = core_service.get_user_by_id(db, listing.owner_id)
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That listing isn't available.",
        )
    return service.serialize_public(db, listing, seller)


@router.get("/board/{listing_id}", response_model=schemas.ListingPublic)
def board_one(listing_id: uuid.UUID, db: Session = Depends(get_db)):
    return _board_one(db, listing_id)


@router.get("/public/board/{listing_id}", response_model=schemas.ListingPublic)
def public_board_one(listing_id: uuid.UUID, db: Session = Depends(get_db)):
    return _board_one(db, listing_id)


# -- owner surfaces -------------------------------------------------------------------


@router.get("/mine", response_model=list[schemas.OwnerListingPublic])
def my_listings(
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    return [
        service.serialize_owner(db, listing, user)
        for listing in service.displayable(db, service.list_mine(db, user.id))
    ]


@router.post(
    "/listings",
    response_model=schemas.OwnerListingPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_listing(
    payload: schemas.ListingCreate,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    # A listing is born ACTIVE = published: the gate runs first.
    _publish_gate(db, user.id)
    try:
        # exclude_unset is LOAD-BEARING here: the schema's defaults
        # (title "" above all) must not masquerade as seller input —
        # with a source item, the snapshot fills what the seller
        # didn't send, and only what they DID send may override it.
        listing = service.create_listing(
            db, user, payload.model_dump(exclude_unset=True)
        )
    except service.MarketplaceError as exc:
        raise _as_http(exc)
    return service.serialize_owner(db, listing, user)


@router.get("/listings/{listing_id}", response_model=schemas.OwnerListingPublic)
def get_my_listing(
    listing_id: uuid.UUID,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    try:
        listing = service.owned_listing(db, user.id, listing_id)
    except service.MarketplaceError as exc:
        raise _as_http(exc)
    return service.serialize_owner(db, listing, user)


@router.put("/listings/{listing_id}", response_model=schemas.OwnerListingPublic)
def update_listing(
    listing_id: uuid.UUID,
    payload: schemas.ListingUpdate,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    try:
        existing = service.owned_listing(db, user.id, listing_id)
    except service.MarketplaceError as exc:
        raise _as_http(exc)
    # Editing an ACTIVE listing is editing a publication — the
    # gate applies. Editing a sold/removed one is bookkeeping.
    if existing.status == "active":
        _publish_gate(db, user.id)
    try:
        listing = service.update_listing(
            db, user.id, listing_id, payload.model_dump(exclude_unset=True)
        )
    except service.MarketplaceError as exc:
        raise _as_http(exc)
    return service.serialize_owner(db, listing, user)


@router.delete("/listings/{listing_id}", status_code=204)
def delete_listing(
    listing_id: uuid.UUID,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    if not service.delete_listing(db, user.id, listing_id):
        raise HTTPException(status_code=404, detail="Listing not found")


@router.post(
    "/listings/{listing_id}/sold", response_model=schemas.OwnerListingPublic
)
def mark_sold(
    listing_id: uuid.UUID,
    payload: schemas.MarkSoldRequest,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    try:
        listing, _interaction = service.mark_sold(
            db,
            user,
            listing_id,
            buyer_user_id=payload.buyer_user_id,
            buyer_account_number=payload.buyer_account_number,
        )
    except service.MarketplaceError as exc:
        raise _as_http(exc)
    return service.serialize_owner(db, listing, user)


@router.post(
    "/listings/{listing_id}/remove", response_model=schemas.OwnerListingPublic
)
def remove_listing(
    listing_id: uuid.UUID,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    try:
        listing = service.remove_listing(db, user.id, listing_id)
    except service.MarketplaceError as exc:
        raise _as_http(exc)
    return service.serialize_owner(db, listing, user)


@router.post(
    "/listings/{listing_id}/reactivate",
    response_model=schemas.OwnerListingPublic,
)
def reactivate_listing(
    listing_id: uuid.UUID,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    try:
        listing = service.owned_listing(db, user.id, listing_id)
    except service.MarketplaceError as exc:
        raise _as_http(exc)
    if listing.status == "removed":
        _publish_gate(db, user.id)
    try:
        listing = service.reactivate_listing(db, user.id, listing_id)
    except service.MarketplaceError as exc:
        raise _as_http(exc)
    return service.serialize_owner(db, listing, user)


@router.get(
    "/listings/{listing_id}/buyer-candidates",
    response_model=list[schemas.BuyerCandidate],
)
def buyer_candidates(
    listing_id: uuid.UUID,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    try:
        return service.buyer_candidates(db, user.id, listing_id)
    except service.MarketplaceError as exc:
        raise _as_http(exc)


# -- uploads -------------------------------------------------------------------------


@router.post("/listings/{listing_id}/upload-url", response_model=schemas.UploadUrlResponse)
def get_upload_url(
    listing_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.issue_upload_url(db, user.id, listing_id, payload)
    except attachments.ListingUploadError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Listing not found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=str(exc))


@router.post("/listings/{listing_id}/attachments", response_model=dict)
def attach_file(
    listing_id: uuid.UUID,
    payload: schemas.AttachRequest,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.attach_file(db, user.id, listing_id, payload)
    except attachments.ListingUploadError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Listing not found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=str(exc))


# -- reputation ------------------------------------------------------------------------


@router.get("/interactions/mine", response_model=list[schemas.InteractionPublic])
def my_interactions(
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    """My completed deals, with my rating state and (only once
    published) the other side's rating of me."""
    return [
        reputation.interaction_view(db, user.id, row)
        for row in reputation.interactions_for(db, user.id)
    ]


@router.post(
    "/interactions/{interaction_id}/rating",
    response_model=schemas.InteractionPublic,
    status_code=status.HTTP_201_CREATED,
)
def submit_rating(
    interaction_id: uuid.UUID,
    payload: schemas.RatingCreate,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    try:
        reputation.submit_rating(
            db, user, interaction_id, payload.stars, payload.text
        )
        interaction = reputation.participant_interaction(db, user.id, interaction_id)
    except reputation.ReputationError as exc:
        raise _as_http(exc)
    return reputation.interaction_view(db, user.id, interaction)


@router.post(
    "/threads/{thread_id}/complete",
    response_model=schemas.ThreadCompletionPublic,
)
def complete_thread(
    thread_id: uuid.UUID,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    """Close an anchored conversation as a completed deal (my
    side). When the other side has also closed, the deal becomes
    a rateable interaction. The thread itself is messaging's —
    participation is validated through its service."""
    from app.modules.messaging import service as messaging_service

    try:
        thread = messaging_service.participant_thread(db, user.id, thread_id)
        return reputation.complete_thread(db, user, thread)
    except (messaging_service.MessagingError, reputation.ReputationError) as exc:
        raise _as_http(exc)


@router.get("/threads/{thread_id}/completion", response_model=schemas.ThreadCompletionPublic)
def thread_completion(
    thread_id: uuid.UUID,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    from app.modules.messaging import service as messaging_service

    try:
        thread = messaging_service.participant_thread(db, user.id, thread_id)
    except messaging_service.MessagingError as exc:
        raise _as_http(exc)
    return reputation.thread_completion_state(db, thread, user.id)


@router.get("/reputation/{user_id}", response_model=schemas.ReputationPublic)
def public_reputation(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """A member's public reputation: the aggregate + published
    reviews. Readable signed out (the profile page links here);
    404s with the board while the marketplace is switched off,
    and for unknown/deactivated accounts."""
    if not service.marketplace_enabled(db):
        raise _board_off()
    target = core_service.get_user_by_id(db, user_id)
    if target is None or not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That member isn't available.",
        )
    return {
        "user_id": target.id,
        "summary": reputation.summary_for(db, target.id),
        "ratings": reputation.published_ratings_for(db, target.id),
    }


# -- rating moderation (gap wave 1, 2026-10-20) --------------------------------
#
# Reports are filed by any signed-in member against a published
# rating (the marketplace module gate — the same door the rest of
# the member surfaces use). The queue itself rides the community
# ROLE LADDER (moderator / community_admin) plus operators — the
# messaging/forum queue's gate, mirrored here so no feature
# module imports another's routes.

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


@router.post(
    "/ratings/{rating_id}/report",
    response_model=schemas.RatingReportPublic,
    status_code=status.HTTP_201_CREATED,
)
def report_rating(
    rating_id: uuid.UUID,
    payload: schemas.RatingReportCreate,
    user: CurrentUser = Depends(_marketplace_module),
    db: Session = Depends(get_db),
):
    """Report a published review as abusive. Lands in the
    moderation queue's Ratings section."""
    if not service.marketplace_enabled(db):
        raise _board_off()
    try:
        row = reputation.report_rating(db, user, rating_id, payload.reason)
    except reputation.ReputationError as exc:
        raise _as_http(exc)
    return reputation.rating_report_view(db, row)


@router.get(
    "/mod/rating-reports", response_model=list[schemas.RatingReportPublic]
)
def mod_rating_reports(
    status_filter: str = "open",
    _moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    return reputation.list_rating_reports(db, status_filter)


@router.post(
    "/mod/rating-reports/{report_id}/dismiss",
    response_model=schemas.RatingReportPublic,
)
def mod_dismiss_rating_report(
    report_id: uuid.UUID,
    payload: schemas.RatingReportResolve,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    try:
        return reputation.dismiss_rating_report(
            db, moderator, report_id, payload.resolution
        )
    except reputation.ReputationError as exc:
        raise _as_http(exc)


@router.post(
    "/mod/rating-reports/{report_id}/remove",
    response_model=schemas.RatingReportPublic,
)
def mod_remove_rating(
    report_id: uuid.UUID,
    payload: schemas.RatingReportResolve,
    moderator: CurrentUser = Depends(require_moderator),
    db: Session = Depends(get_db),
):
    """Remove the reported rating: it stops counting toward every
    aggregate and its text becomes the moderator placeholder."""
    try:
        return reputation.remove_rating_for_report(
            db, moderator, report_id, payload.resolution
        )
    except reputation.ReputationError as exc:
        raise _as_http(exc)
