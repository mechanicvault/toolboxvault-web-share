"""Wire shapes for the catalog module (wave 4)."""

from pydantic import BaseModel, Field


class LookupField(BaseModel):
    value: str | float | int
    source: str  # community | barcode | web | ai
    detail: str
    # Community-sourced fields only: how many distinct owners
    # agree (the catalog read contract). Other sources omit it.
    supporters: int | None = None


class LookupResponse(BaseModel):
    fields: dict[str, LookupField]
    sources: list[str]
    ai_charged: int = 0
    # Grounded-lookup contract (2026-10-25): partial = real
    # details but no verified name — the UI says so plainly
    # instead of dressing it up as a hit. image_url is the
    # product page's real photo (never invented); source_name /
    # source_url name the page the web facts were read from;
    # web_configured says whether the web search layer is
    # switched on (it rides the AI seam — on exactly when the
    # AI is configured); link_error says a pasted page couldn't be
    # read (or yielded nothing usable) — the UI shows the
    # couldn't-read-that-page note and never guesses instead.
    partial: bool = False
    # Photo identification only (2026-11-07): the model's own
    # stated confidence in its read — "high" | "medium" |
    # "low" — so the wizard can say plainly how sure the AI is
    # before the user lets the identification drive a lookup.
    # Every other surface omits it.
    confidence: str | None = None
    # Mismatch honesty (C-08): model_mismatch = the winning
    # page's model differs from the model the user typed (a
    # variant — kit / tool-only suffix); found_model is that
    # page's model, so the card can name it in plain words
    # instead of silently prefilling it as the typed one.
    model_mismatch: bool = False
    found_model: str | None = None
    image_url: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    web_configured: bool = False
    link_error: bool = False


class FetchPhotoRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class FetchPhotoResponse(BaseModel):
    filename: str
    content_type: str
    data_base64: str


class CatalogSuggestions(BaseModel):
    """The raw community aggregate for one product key."""

    brand: str
    model: str
    contributors: int
    fields: dict[str, dict]


class IdentifyRequest(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


class IdentifyPhotoRequest(BaseModel):
    """One photo of the item (or its label) as base64 — the
    wizard reads the picked file in the browser and posts the
    bytes; the service byte-sniffs the real type and enforces
    the 8 MB decoded cap (the max_length here is that cap in
    base64 characters, with headroom)."""

    image_base64: str = Field(min_length=16, max_length=11_200_000)
