"""Used Parts module request/response shapes."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# -- locations -------------------------------------------------------------
class PartLocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # warehouse | aisle | bin | shelf | other — validated in the service
    # against models.LOCATION_LEVELS for a friendly error.
    level: str = "other"
    parent_id: uuid.UUID | None = None


class PartLocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    level: str | None = None
    # parent_id is EXPLICIT-nullable: sending null moves the node to
    # the root; omitting it leaves the parent alone (the service
    # distinguishes via model_fields_set).
    parent_id: uuid.UUID | None = None


class PartLocationDelete(BaseModel):
    """Deleting a node that still holds parts or children needs an
    explicit answer: reassign them to another node, or detach=true
    (children move up to this node's parent, parts become unfiled).
    With neither, the service refuses with friendly copy."""

    reassign_to_id: uuid.UUID | None = None
    detach: bool = False


class PartLocationPublic(BaseModel):
    id: uuid.UUID
    name: str
    level: str
    parent_id: uuid.UUID | None
    # Parts filed directly at this node, and the subtree rollup
    # (this node + every descendant) — the tree manager shows both.
    own_count: int = 0
    part_count: int = 0
    created_at: datetime
    updated_at: datetime


# -- parts -------------------------------------------------------------------
class AttachmentPublic(BaseModel):
    key: str
    filename: str
    kind: str
    content_type: str
    size_bytes: int
    uploaded_at: str | None = None
    url: str  # fresh presigned read URL, minted at read time


class PartLocationRef(BaseModel):
    """Where a part sits: the node plus its full root-to-node path."""

    id: uuid.UUID
    name: str
    level: str
    path: str


class PartCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    quantity: int = Field(default=1, ge=1, le=100000)
    condition: str = Field(default="", max_length=50)
    notes: str = Field(default="", max_length=10000)
    location_id: uuid.UUID | None = None
    # Values keyed by field-definition id (or name slug), validated
    # in the service against the owner's 'part' definitions.
    custom_data: dict = {}
    # Community pool (2026-10-19): the standard vehicle fields the
    # community index searches on, the owner's category label, and
    # the optional listing facts. Defaults keep the plain shelf
    # flow exactly as before — all of this is opt-in.
    year: int | None = Field(default=None, ge=1885, le=2100)
    make: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=150)
    engine: str = Field(default="", max_length=100)
    category: str = Field(default="", max_length=100)
    asking_price: Decimal | None = Field(default=None, ge=0)
    public_area_label: str | None = Field(default=None, max_length=120)
    # The part's visibility override: "public" | "private" | null
    # (inherit the category setting, then the pool default).
    visibility: str | None = Field(default=None, pattern="^(public|private)$")
    show_phone_override: bool | None = None


class PartUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    quantity: int | None = Field(default=None, ge=1, le=100000)
    condition: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=10000)
    # Explicit-nullable: null unfiles the part; omitted keeps it.
    location_id: uuid.UUID | None = None
    custom_data: dict | None = None
    # Community pool fields — all explicit-nullable like
    # location_id: null CLEARS the value/override, omitted keeps.
    year: int | None = Field(default=None, ge=1885, le=2100)
    make: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=150)
    engine: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    asking_price: Decimal | None = Field(default=None, ge=0)
    public_area_label: str | None = Field(default=None, max_length=120)
    visibility: str | None = Field(default=None, pattern="^(public|private)$")
    show_phone_override: bool | None = None


class PartPublic(BaseModel):
    id: uuid.UUID
    title: str
    quantity: int
    condition: str
    notes: str
    location_id: uuid.UUID | None
    location: PartLocationRef | None
    custom_data: dict
    attachments: list[AttachmentPublic] = []
    converted_tool_id: uuid.UUID | None
    # Community pool (2026-10-19).
    year: int | None = None
    make: str = ""
    model: str = ""
    engine: str = ""
    category: str = ""
    asking_price: Decimal | None = None
    public_area_label: str | None = None
    visibility_override: str | None = None
    show_phone_override: bool | None = None
    # The RESOLVED visibility (override > category > pool
    # default) and whether the part is actually listed right now
    # (resolved public AND the pool itself is switched on).
    visibility: str = "private"
    is_public: bool = False
    created_at: datetime
    updated_at: datetime


# -- community pool --------------------------------------------------------------


class PoolSettingsPublic(BaseModel):
    default_visibility: str
    category_visibility: dict[str, str] = {}


class PoolSettingsUpdate(BaseModel):
    default_visibility: str | None = Field(
        default=None, pattern="^(public|private)$"
    )
    category_visibility: dict[str, str] | None = None


class ListingPhoto(BaseModel):
    filename: str
    url: str


class CommunityListingPublic(BaseModel):
    """THE pool listing payload — the exact-key privacy contract
    in pool.py's docstring. The same shape answers the signed-in
    and the anonymous public route."""

    id: uuid.UUID
    title: str
    quantity: int
    condition: str
    category: str
    year: int | None
    make: str
    model: str
    engine: str
    asking_price: Decimal | None
    area_label: str | None
    photos: list[ListingPhoto] = []
    seller_id: uuid.UUID
    seller_name: str
    seller_member_since: datetime
    # Wave 3: the asking price's currency (the seller's).
    seller_currency: str = "USD"
    phone: str | None
    created_at: datetime
    updated_at: datetime


class PartConvertResponse(BaseModel):
    part: PartPublic
    tool_id: uuid.UUID


class PartsStats(BaseModel):
    parts_count: int  # part records (entries on the shelf)
    total_units: int  # sum of quantities across those records


# -- uploads (the shared attachment machinery, photo kind) -------------------
class UploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=127)
    kind: str = "photo"  # parts carry photos only
    size_bytes: int | None = Field(default=None, gt=0)


class UploadUrlResponse(BaseModel):
    upload_url: str
    key: str
    expires_in: int


class AttachRequest(BaseModel):
    key: str = Field(min_length=1)
    filename: str = ""
