"""3D print files request/response schemas.

Reads answer plain dicts built by the service (the forum's
posture — the views carry resolved publisher names and the
viewer's own rating, which a static schema can't express);
these models cover the JSON write bodies.
"""

import uuid

from pydantic import BaseModel, Field


class VisitCountView(BaseModel):
    """The prints page visitor counter's whole public answer
    (owner order, 2026-11-10 — the teaser/Downloads counter's
    shape): the page's unique-visitor count as a bare number;
    the page renders it as digits with no words, and nothing
    else about the visit rides in the response."""

    count: int


class RateRequest(BaseModel):
    stars: int = Field(ge=1, le=5)


class FollowRequest(BaseModel):
    """The per-file update opt-in flip (sweep E4): the listing
    page's follow toggle states the desired state outright."""

    following: bool


class FollowView(BaseModel):
    following: bool


class CommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class ReportRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class RemoveRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class DismissRequest(BaseModel):
    resolution: str = Field(default="", max_length=1000)


class LinkRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=600)


class ListingEditRequest(BaseModel):
    """The publisher's listing edit: title, description,
    category. Bounds mirror the publish form's; the service
    cleans (strip + cap) the same way it does at publish."""

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    category: str = Field(min_length=1, max_length=48)


class MediaOrderRequest(BaseModel):
    """The edit page restates the media order as the full
    id list, in order (five photos + the one video at most)."""

    media_ids: list[uuid.UUID] = Field(max_length=6)


class IdResponse(BaseModel):
    id: uuid.UUID
