"""Feedback boards schemas: the exact-key member payloads.

The shapes are the contract — serializers in service.py build
dicts with exactly these keys, and both read faces (the plain
routes and the /public twins) share them for registered
callers. No email field exists anywhere in this module's
shapes, by construction.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AuthorPublic(BaseModel):
    user_id: uuid.UUID
    display_name: str
    account_number: str = ""
    member_since: datetime | None = None
    role: str = "user"


class PostPublic(BaseModel):
    id: uuid.UUID
    board: str
    title: str
    body: str
    author: AuthorPublic
    status: str
    # Derived closure (sweep E5): true exactly when status is
    # done/declined. Plainly named — the board assistant watcher
    # keys on this field in the list + detail payloads.
    closed: bool = False
    status_note: str = ""
    urgency: str = "medium"
    visibility: str
    vote_count: int = 0
    comment_count: int = 0
    voted_by_me: bool = False
    mine: bool = False
    created_at: datetime
    updated_at: datetime


class CommentPublic(BaseModel):
    id: uuid.UUID
    post_id: uuid.UUID
    author: AuthorPublic
    body: str
    visibility: str
    mine: bool = False
    created_at: datetime


class PostDetailPublic(PostPublic):
    comments: list[CommentPublic] = []


class PostWrite(BaseModel):
    board: str = Field(pattern="^(bug|feature)$")
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    # The filer's urgency call (owner 2026-11-06): picked on
    # the form's 3-position toggle; absent = the toggle's own
    # default, medium. Set once here — the filer has no edit
    # path afterwards.
    urgency: str = Field(default="medium", pattern="^(low|medium|high)$")


class UrgencyWrite(BaseModel):
    # The moderator-side urgency lever (the filer's is locked
    # at submission — there is deliberately no member route
    # carrying this shape).
    urgency: str = Field(pattern="^(low|medium|high)$")


class CommentWrite(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class StatusWrite(BaseModel):
    status: str = Field(
        pattern="^(open|acknowledged|planned|in_progress|done|declined)$"
    )
    note: str = Field(default="", max_length=500)


class ReportWrite(BaseModel):
    target_kind: str = Field(pattern="^(post|comment)$")
    target_id: uuid.UUID
    reason: str = Field(default="", max_length=500)


class ReportPublic(BaseModel):
    id: uuid.UUID
    target_kind: str
    target_id: uuid.UUID
    post_id: uuid.UUID | None = None
    post_title: str = ""
    target_excerpt: str = ""
    target_author_name: str = ""
    target_author_id: uuid.UUID | None = None
    reporter_name: str = ""
    reason: str = ""
    status: str
    created_at: datetime


class HeldPublic(BaseModel):
    id: uuid.UUID
    target_kind: str
    post_id: uuid.UUID
    post_title: str = ""
    author_name: str = ""
    author_id: uuid.UUID
    body: str = ""
    flags: list[str] = []
    created_at: datetime


class DismissWrite(BaseModel):
    note: str = Field(default="", max_length=500)


class RemoveWrite(BaseModel):
    reason: str = Field(default="", max_length=500)
