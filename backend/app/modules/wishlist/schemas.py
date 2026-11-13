"""Wishlist module schemas — the wire shapes."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


def _non_blank(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("Title can't be blank.")
    return stripped


class WishlistStats(BaseModel):
    items_count: int


class WishlistItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)

    _title_non_blank = field_validator("title")(_non_blank)
    link_url: str = Field(default="", max_length=1000)
    target_price: Decimal | None = Field(default=None, ge=0)
    priority: str = "normal"
    dealer_company_id: uuid.UUID | None = None
    notes: str = ""


class WishlistItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("title")
    @classmethod
    def _title_non_blank(cls, value: str | None) -> str | None:
        return None if value is None else _non_blank(value)
    link_url: str | None = Field(default=None, max_length=1000)
    target_price: Decimal | None = Field(default=None, ge=0)
    priority: str | None = None
    dealer_company_id: uuid.UUID | None = None
    notes: str | None = None


class AttachmentPublic(BaseModel):
    key: str
    filename: str
    kind: str
    content_type: str
    size_bytes: int
    uploaded_at: str | None = None
    url: str


class WishlistItemPublic(BaseModel):
    id: uuid.UUID
    title: str
    link_url: str
    target_price: Decimal | None
    priority: str
    dealer_company_id: uuid.UUID | None
    dealer_name: str | None
    notes: str
    attachments: list[AttachmentPublic]
    status: str
    purchased_price: Decimal | None
    purchased_on: date | None
    converted_tool_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class MarkPurchased(BaseModel):
    purchased_price: Decimal = Field(ge=0)
    purchased_on: date | None = None  # defaults to today, service-side


class ConvertResponse(BaseModel):
    item: WishlistItemPublic
    tool_id: uuid.UUID


class UploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=127)
    kind: str = "photo"  # wishlist items carry photos only
    size_bytes: int | None = Field(default=None, gt=0)


class UploadUrlResponse(BaseModel):
    upload_url: str
    key: str
    expires_in: int


class AttachRequest(BaseModel):
    key: str = Field(min_length=1)
    filename: str = ""
