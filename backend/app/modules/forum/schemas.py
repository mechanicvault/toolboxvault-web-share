"""Community Forum request/response shapes."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReputationSummary(BaseModel):
    """The ONE aggregate shape (marketplace reputation.summary_for)."""

    average: float | None = None
    count: int = 0
    completed_deals: int = 0


class AuthorPublic(BaseModel):
    """The public author identity — exact keys. Display name,
    account number, member since, role, reputation. Never an
    email, never a phone."""

    user_id: uuid.UUID
    display_name: str
    account_number: str
    member_since: datetime | None
    role: str
    reputation: ReputationSummary


class CategoryPublic(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    sort_order: int
    is_active: bool
    # Built-in rooms carry their system key (migration 0070);
    # operator rooms carry None. "bug_reports"/"feature_requests"
    # are the PERMANENT boards; "site_help" is the Help &
    # Support community room.
    system_key: str | None = None
    thread_count: int
    post_count: int
    last_thread_id: uuid.UUID | None
    last_thread_title: str | None
    last_activity_at: datetime | None


class LinkCard(BaseModel):
    """An attached community reference, resolved live: a live
    target carries its current title/price/photo; a dead one
    carries available=False + the snapshotted title."""

    type: str
    id: uuid.UUID
    title: str
    price: Decimal | None
    seller_currency: str | None
    photo_url: str | None
    available: bool


class QuotePublic(BaseModel):
    author_name: str
    excerpt: str


class PostPublic(BaseModel):
    """One post in a thread — exact keys, same shape on the
    signed-in and anonymous routes."""

    id: uuid.UUID
    thread_id: uuid.UUID
    author: AuthorPublic
    body: str
    status: str
    removed_by: str | None
    is_opener: bool
    quote: QuotePublic | None
    link: LinkCard | None
    flags: list[str] = []
    edited_at: datetime | None
    created_at: datetime
    mine: bool


class ThreadPublic(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    title: str
    author: AuthorPublic
    pinned: bool
    locked: bool
    held: bool
    reply_count: int
    post_count: int
    excerpt: str
    created_at: datetime
    last_post_at: datetime


class ThreadDetailPublic(ThreadPublic):
    posts: list[PostPublic] = []


class ThreadCreate(BaseModel):
    category_id: uuid.UUID
    title: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=20000)
    link_type: str = Field(default="", max_length=20)
    link_id: uuid.UUID | None = None


class ReplyCreate(BaseModel):
    body: str = Field(default="", max_length=20000)
    quote_post_id: uuid.UUID | None = None
    link_type: str = Field(default="", max_length=20)
    link_id: uuid.UUID | None = None


class PostEdit(BaseModel):
    body: str = Field(default="", max_length=20000)


class ReportCreate(BaseModel):
    reason: str = Field(default="", max_length=500)


class ReportResolve(BaseModel):
    resolution: str = Field(default="", max_length=500)


class BlockCreate(BaseModel):
    """A community block (admin lane, owner 2026-11-06): the
    member resolves by id OR by exact account number; feature
    is one of the community feature keys; reason is the
    plain-words why the member sees in their notice."""

    user_id: uuid.UUID | None = None
    account_number: str = Field(default="", max_length=20)
    feature: str = Field(max_length=32)
    reason: str = Field(default="", max_length=500)


class BlockPublic(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    account_number: str
    feature: str
    feature_label: str
    reason: str
    blocked_by_id: uuid.UUID
    blocked_by_name: str
    lifted_by_id: uuid.UUID | None
    lifted_by_name: str
    lifted_at: datetime | None
    active: bool
    created_at: datetime


class ReportPublic(BaseModel):
    id: uuid.UUID
    post_id: uuid.UUID
    thread_id: uuid.UUID
    thread_title: str
    post_status: str
    post_excerpt: str
    post_author_id: uuid.UUID | None
    post_author_name: str
    reporter_id: uuid.UUID
    reporter_name: str
    reason: str
    status: str
    resolution: str
    resolved_by_id: uuid.UUID | None
    resolved_at: datetime | None
    created_at: datetime


class HeldPublic(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    thread_title: str
    author_id: uuid.UUID
    author_name: str
    body: str
    flags: list[str] = []
    is_opener: bool
    created_at: datetime


class WipeResult(BaseModel):
    user_id: uuid.UUID
    posts_removed: int


class FavoriteCreate(BaseModel):
    # "thread" (a forum thread) | "post" (a permanent board's
    # feedback post) — models.FAVORITE_KINDS; the service refuses
    # anything else with a friendly 422.
    kind: str = Field(default="", max_length=20)
    target_id: uuid.UUID


class FavoritePublic(BaseModel):
    """One resolved favorite — the target's LIVE face (title,
    board, reply count, last activity), resolved at read time
    so a favorite never shows a stale snapshot. Targets the
    member can no longer see never reach this shape at all:
    the list silently drops them."""

    kind: str
    target_id: uuid.UUID
    title: str
    board_name: str
    reply_count: int
    last_activity_at: datetime
    starred_at: datetime


class CategoryCreate(BaseModel):
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=2000)
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    sort_order: int | None = None
    is_active: bool | None = None
