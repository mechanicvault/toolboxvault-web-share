"""Flyers wire shapes (Pydantic v2)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class FlyerView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    page_count: int
    origin: str
    starts_on: date
    ends_on: date
    thumb_url: str | None
    pdf_url: str | None
    is_current: bool
    created_at: datetime


class SourceView(BaseModel):
    id: uuid.UUID | None
    key: str
    kind: str
    company_id: uuid.UUID
    company_name: str
    agent_user_id: uuid.UUID | None
    private_agent_id: uuid.UUID | None
    agent_name: str
    visible: bool
    history_visible: bool
    standing_url: str
    can_post: bool
    current: FlyerView | None
    history: list[FlyerView]


class CompanyTabView(BaseModel):
    company_id: uuid.UUID
    sources: list[SourceView]
    postable: list[SourceView]


class SourceCreate(BaseModel):
    kind: str
    company_id: uuid.UUID
    agent_user_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID | None = None


class SourceSettings(BaseModel):
    visible: bool | None = None
    history_visible: bool | None = None
    standing_url: str | None = None


class LinkPost(BaseModel):
    url: str
    label: str = ""
    starts_on: date
    ends_on: date


class UploadPost(BaseModel):
    key: str
    label: str = ""
    starts_on: date
    ends_on: date


class UploadUrlRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int | None = None


class UploadUrlResponse(BaseModel):
    upload_url: str
    key: str
    expires_in: int


class DetectRequest(BaseModel):
    keys: list[str]


class DetectPage(BaseModel):
    key: str
    width: int
    height: int
    corners: list[list[float]]
    detected: bool


class PhotoPage(BaseModel):
    key: str
    corners: list[list[float]]


class PhotosPost(BaseModel):
    pages: list[PhotoPage]
    label: str = ""
    starts_on: date
    ends_on: date


class AlertPrefView(BaseModel):
    enabled: bool


class AlertPrefWrite(BaseModel):
    enabled: bool
