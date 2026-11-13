"""Downloads module request/response schemas (Pydantic v2)."""

import re
from datetime import datetime

from pydantic import BaseModel, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Signup sources the store recognizes: the generic downloads
# mark (the default, what the old sheet gate used) and the
# voluntary news signup on the downloads page's About tab
# (owner order 2026-11-08). Anything else an anonymous caller
# sends clamps to the generic mark — the column is a record
# for us, not a free-text field.
_SUBSCRIBE_SOURCES = {"downloads", "downloads-news"}


class SubscribeRequest(BaseModel):
    email: str
    source: str = "downloads"

    @field_validator("source")
    @classmethod
    def _clean_source(cls, value: str) -> str:
        cleaned = value.strip().lower()
        return cleaned if cleaned in _SUBSCRIBE_SOURCES else "downloads"

    @field_validator("email")
    @classmethod
    def _clean_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if len(cleaned) > 320 or not _EMAIL_RE.match(cleaned):
            raise ValueError("That email address doesn't look right.")
        return cleaned


class SubscribeResponse(BaseModel):
    ok: bool = True


class SheetRequest(BaseModel):
    preset: str = "generic"
    fields: list[str] | None = None
    personal_header: bool = False


class CatalogFile(BaseModel):
    key: str
    format: str
    filename: str
    download_count: int


class CatalogResponse(BaseModel):
    files: list[CatalogFile]


class WallpaperSizeView(BaseModel):
    """One device size of one artwork: its honest pixel
    dimensions and its own download count."""

    size: str
    width: int
    height: int
    download_count: int


class WallpaperView(BaseModel):
    """One artwork on the Wallpaper shelf: the count the tile
    shows is the sum of its sizes' counts."""

    key: str
    branded: bool
    category: str
    download_count: int
    sizes: list[WallpaperSizeView]


class WallpaperCatalogResponse(BaseModel):
    wallpapers: list[WallpaperView]


class InspectionRequest(BaseModel):
    """The inspection wizard's posted choices (owner order
    2026-11-09). Shop info is all optional — whatever is given
    brands the generated PDF's header. `items` is the list of
    selected item keys; None (untouched wizard) means every
    item on. `lang` is the language the visitor is browsing in;
    anything unrecognized clamps to English."""

    shop_name: str = ""
    shop_address: str = ""
    shop_phone: str = ""
    items: list[str] | None = None
    lang: str = "en"

    @field_validator("shop_name")
    @classmethod
    def _clean_shop_name(cls, value: str) -> str:
        return " ".join((value or "").split())[:60]

    @field_validator("shop_address")
    @classmethod
    def _clean_shop_address(cls, value: str) -> str:
        return " ".join((value or "").split())[:90]

    @field_validator("shop_phone")
    @classmethod
    def _clean_shop_phone(cls, value: str) -> str:
        return " ".join((value or "").split())[:30]

    @field_validator("lang")
    @classmethod
    def _clean_lang(cls, value: str) -> str:
        cleaned = (value or "").strip().lower()
        return cleaned if cleaned in ("en", "es") else "en"


class TopWindowItem(BaseModel):
    """One shelf entry in the window ranking: a document by
    its own key, or a wallpaper by its artwork key (its size
    downloads already summed), with the downloads the dated
    event record saw inside the window."""

    key: str
    kind: str  # "document" | "wallpaper"
    count: int


class TopWindowResponse(BaseModel):
    """The top-downloading shelf entries over the last
    `window_days` days (dashboard-flare lane, 2026-11-09).
    `tracking_since` is when the dated event record began —
    null while it holds nothing — so a reader can label a
    young window honestly instead of dressing a few days up
    as a full week."""

    window_days: int
    tracking_since: datetime | None
    items: list[TopWindowItem]


class VisitCountView(BaseModel):
    """The Downloads visitor counter's whole public answer
    (owner order, 2026-11-08 — the teaser counter's shape): the
    page's unique-visitor count as a bare number; the page
    renders it as digits with no words, and nothing else about
    the visit rides in the response."""

    count: int
