"""Support ticket schemas: the exact-key payloads.

User face: a ticket summary (list rows) and a ticket detail (the
ticket + its messages). The operator face adds the owner's
identity (name / email / account number) so the support desk can
tell whose ticket it is — those fields exist ONLY on the admin
shapes.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)


class MessageWrite(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class StatusWrite(BaseModel):
    status: str = Field(pattern="^(open|under_review|closed)$")


class SupportStats(BaseModel):
    open_tickets_count: int


class MessagePublic(BaseModel):
    id: uuid.UUID
    author_kind: str
    body: str
    created_at: datetime


class TicketSummary(BaseModel):
    id: uuid.UUID
    subject: str
    status: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message_preview: str = ""
    # "user" | "operator" | "" (no messages): whose message is
    # newest — the help page's status strip reads it.
    last_message_author_kind: str = ""


class TicketDetail(TicketSummary):
    messages: list[MessagePublic] = []


class AdminTicketSummary(TicketSummary):
    user_id: uuid.UUID
    user_name: str = ""
    user_email: str = ""
    user_account_number: str = ""


class AdminTicketDetail(TicketDetail):
    user_id: uuid.UUID
    user_name: str = ""
    user_email: str = ""
    user_account_number: str = ""


# -- how-to videos (Help & Support build, 2026-11-02) -----------------


class HelpVideoPublic(BaseModel):
    """The member face: published videos only."""

    id: uuid.UUID
    title: str
    summary: str = ""
    youtube_id: str
    section: str
    sort_order: int = 0


class AdminHelpVideo(HelpVideoPublic):
    is_published: bool = False
    created_at: datetime
    updated_at: datetime


class HelpVideoWrite(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=1000)
    # A YouTube watch/short/embed URL or the bare video id —
    # the service normalizes it to the id and validates it.
    youtube: str = Field(min_length=1, max_length=500)
    section: str = Field(pattern="^(website|app)$")
    sort_order: int = 0
    is_published: bool = False
