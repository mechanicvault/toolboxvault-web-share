"""Messaging module request/response shapes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ThreadOpen(BaseModel):
    """Open (or continue) a conversation. anchor_type "part"
    anchors it to a Community Parts listing: the recipient must
    be the listing's owner — the route resolves the listing."""

    recipient_id: uuid.UUID
    body: str = Field(min_length=1, max_length=5000)
    anchor_type: str = Field(default="", max_length=30)
    anchor_id: uuid.UUID | None = None


class MessageSend(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ReportCreate(BaseModel):
    reason: str = Field(default="", max_length=500)


class BlockCreate(BaseModel):
    user_id: uuid.UUID


class MessagePublic(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    sender_id: uuid.UUID
    mine: bool
    body: str
    status: str
    held: bool
    removed: bool
    flags: list[str] = []
    has_links: bool
    links_disabled: bool
    created_at: datetime
    seq: int


class ThreadPublic(BaseModel):
    id: uuid.UUID
    other_user_id: uuid.UUID
    other_name: str
    anchor_type: str
    anchor_id: uuid.UUID | None
    anchor_title: str
    status: str
    # request threads are directional: "incoming" waits on me,
    # "outgoing" waits on them; accepted threads read "accepted".
    direction: str
    unread_count: int
    other_last_read_seq: int | None
    last_message_at: datetime | None
    last_message_preview: str
    last_message_sender_id: uuid.UUID | None
    last_message_mine: bool
    message_count: int
    created_at: datetime
    updated_at: datetime


class ThreadDetail(ThreadPublic):
    messages: list[MessagePublic] = []


class UnreadSummary(BaseModel):
    inbox_unread: int
    requests_count: int


class RecipientLookup(BaseModel):
    user_id: uuid.UUID
    display_name: str


class BlockPublic(BaseModel):
    user_id: uuid.UUID
    name: str
    created_at: datetime


class ReputationSummary(BaseModel):
    """The reputation aggregate (marketplace's engine): average +
    count over PUBLISHED ratings, plus completed deals. A member
    with no published ratings reads average None / count 0 —
    honest zeros, never invented numbers."""

    average: float | None = None
    count: int = 0
    completed_deals: int = 0


class PublicProfile(BaseModel):
    user_id: uuid.UUID
    display_name: str
    member_since: datetime
    area_label: str | None
    show_phone: bool
    # Present ONLY while the owner opted in (profile toggle, or a
    # part-level override on that part's listing). Absent-value,
    # never an empty string dressed as a number.
    phone: str | None
    reputation: ReputationSummary


# -- moderation -----------------------------------------------------------------


class ReportPublic(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    reporter_id: uuid.UUID
    reporter_name: str
    reason: str
    status: str
    resolution: str
    resolved_by_id: uuid.UUID | None
    resolved_at: datetime | None
    created_at: datetime
    anchor_title: str
    participant_names: list[str] = []


class HeldPublic(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    sender_id: uuid.UUID
    sender_name: str
    recipient_id: uuid.UUID | None
    recipient_name: str
    body: str
    status: str
    flags: list[str] = []
    anchor_title: str
    created_at: datetime


class ModMessagePublic(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    sender_name: str
    body: str
    status: str
    flags: list[str] = []
    created_at: datetime
    seq: int


class ModThreadPublic(BaseModel):
    id: uuid.UUID
    participant_low_id: uuid.UUID
    participant_high_id: uuid.UUID
    participant_names: list[str] = []
    anchor_type: str
    anchor_id: uuid.UUID | None
    anchor_title: str
    status: str
    created_at: datetime
    messages: list[ModMessagePublic] = []


class ReportResolve(BaseModel):
    resolution: str = Field(default="", max_length=500)


class WipeAllResult(BaseModel):
    user_id: uuid.UUID
    wiped: int
    discarded: int


class BanResult(BaseModel):
    user_id: uuid.UUID
    email: str
    banned: bool
