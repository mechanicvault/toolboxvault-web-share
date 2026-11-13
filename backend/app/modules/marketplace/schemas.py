"""Tools For Sale + reputation request/response shapes."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReputationSummary(BaseModel):
    """The ONE aggregate shape (reputation.summary_for) — the
    same object the messaging profile carries."""

    average: float | None = None
    count: int = 0
    completed_deals: int = 0


class ListingPhoto(BaseModel):
    filename: str
    url: str


class MarketplaceStats(BaseModel):
    active_listings_count: int


class ListingPublic(BaseModel):
    """THE board payload — the exact-key privacy contract in
    service.py's docstring. The same shape answers the signed-in
    and the anonymous public route."""

    id: uuid.UUID
    title: str
    description: str
    listing_type: str
    price: Decimal | None
    condition: str
    brand: str
    model: str
    delivery_local_pickup: bool
    delivery_ships: bool
    area_label: str | None
    photos: list[ListingPhoto] = []
    seller_id: uuid.UUID
    seller_name: str
    seller_member_since: datetime
    seller_reputation: ReputationSummary
    # Wave 3: the price's currency (the seller's).
    seller_currency: str = "USD"
    phone: str | None
    created_at: datetime
    updated_at: datetime


class OwnerListingPublic(ListingPublic):
    """The owner's view of their own listing: the board shape
    plus lifecycle, provenance, and the RAW overrides (the edit
    form shows what it set, not the resolved values)."""

    status: str
    source_kind: str = ""
    source_id: uuid.UUID | None = None
    buyer_id: uuid.UUID | None = None
    buyer_name: str | None = None
    sold_at: datetime | None = None
    area_override: str | None = None
    show_phone_override: bool | None = None


class ListingCreate(BaseModel):
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    listing_type: str = Field(default="for_sale", max_length=20)
    price: Decimal | None = None
    condition: str = Field(default="", max_length=120)
    brand: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    delivery_local_pickup: bool = True
    delivery_ships: bool = False
    public_area_label: str | None = Field(default=None, max_length=120)
    show_phone_override: bool | None = None
    # One-tap create from inventory: the server snapshots the
    # record's display facts; explicit fields above win.
    source_kind: str = Field(default="", max_length=20)
    source_id: uuid.UUID | None = None


class ListingUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    listing_type: str | None = Field(default=None, max_length=20)
    price: Decimal | None = None
    condition: str | None = Field(default=None, max_length=120)
    brand: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    delivery_local_pickup: bool | None = None
    delivery_ships: bool | None = None
    public_area_label: str | None = Field(default=None, max_length=120)
    show_phone_override: bool | None = None


class MarkSoldRequest(BaseModel):
    """The buyer, identified ONE of two ways (or not at all — a
    sale with no identified buyer closes the listing but creates
    no rateable interaction)."""

    buyer_user_id: uuid.UUID | None = None
    buyer_account_number: str | None = Field(default=None, max_length=40)


class BuyerCandidate(BaseModel):
    user_id: uuid.UUID
    name: str


class UploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=300)
    content_type: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="photo", max_length=20)
    size_bytes: int | None = None


class UploadUrlResponse(BaseModel):
    upload_url: str
    key: str
    expires_in: int


class AttachRequest(BaseModel):
    key: str = Field(min_length=1, max_length=600)
    filename: str = Field(default="", max_length=300)


# -- reputation --------------------------------------------------------------------


class RatingCreate(BaseModel):
    stars: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=500)


class MyRatingView(BaseModel):
    # stars/text become null/placeholder when a moderator has
    # removed the rating (gap wave 1) — `removed` says why.
    stars: int | None = None
    text: str
    removed: bool = False
    published: bool
    published_at: datetime | None = None


class TheirRatingView(BaseModel):
    id: uuid.UUID | None = None
    stars: int | None = None
    text: str
    removed: bool = False
    published_at: datetime | None = None


class InteractionPublic(BaseModel):
    """One completed deal as ONE side sees it (reputation's
    blind-honest view: their stars/text exist here ONLY once
    published)."""

    id: uuid.UUID
    source: str
    context_title: str
    listing_id: uuid.UUID | None = None
    part_id: uuid.UUID | None = None
    thread_id: uuid.UUID | None = None
    other_user_id: uuid.UUID
    other_name: str
    completed_at: datetime
    my_rating: MyRatingView | None = None
    their_rating: TheirRatingView | None = None
    their_rating_submitted: bool = False


class PublishedRatingPublic(BaseModel):
    id: uuid.UUID
    # A moderator-removed review renders as a tombstone: stars
    # null, text the placeholder, removed true (gap wave 1).
    stars: int | None = None
    text: str
    removed: bool = False
    rater_id: uuid.UUID
    rater_name: str
    context_title: str
    published_at: datetime | None = None
    created_at: datetime


# -- rating moderation (gap wave 1) ---------------------------------------------


class RatingReportCreate(BaseModel):
    reason: str = Field(default="", max_length=500)


class RatingReportResolve(BaseModel):
    resolution: str = Field(default="", max_length=500)


class RatingReportPublic(BaseModel):
    """One rating report as the moderation queue sees it — the
    report plus the rating it names (stars/text/names/context),
    so a moderator can judge without a second fetch."""

    id: uuid.UUID
    rating_id: uuid.UUID
    reporter_id: uuid.UUID
    reporter_name: str
    reason: str
    status: str
    resolution: str
    resolved_by_id: uuid.UUID | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    rating_stars: int | None = None
    rating_text: str = ""
    rating_removed: bool = False
    rater_id: uuid.UUID | None = None
    rater_name: str = ""
    ratee_id: uuid.UUID | None = None
    ratee_name: str = ""
    context_title: str = ""


class ReputationPublic(BaseModel):
    """A member's public reputation page payload: the aggregate
    plus their published reviews."""

    user_id: uuid.UUID
    summary: ReputationSummary
    ratings: list[PublishedRatingPublic] = []


class ThreadCompletionPublic(BaseModel):
    anchored: bool
    i_closed: bool
    other_closed: bool
    interaction_id: uuid.UUID | None = None
