"""Smart search (wave 4) — a DETERMINISTIC parser over the
inventory search box. No AI: the parser reads the owner's OWN
vocabulary (their brands, categories, locations, tags) plus the
standing vocabulary and price phrases, and turns a typed line
into the existing filter set:

    "snap-on broken under $200"   -> brand text + standing + max
    "in shop toolbox"              -> location filter
    "wrenches tagged aviation"     -> category text + tag filter

Whatever it can't attribute stays as plain text (the ordinary
full-text q). The endpoint returns the parse WITH its chips —
"Searching for: ..." — so the user sees exactly what was
understood (honesty over magic): a filter the parser chose is
never invisible.

parse_smart_query(db, owner_id, q) -> {
    "text": str,                # leftover plain-text query
    "filters": {                # the search endpoints' own params
        "category": str|None, "location": str|None,
        "standing": str|None, "tag_id": str|None,
        "min_price": str|None, "max_price": str|None,
    },
    "chips": [{"kind": ..., "label": ...}],
}
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory import models, service

# Standing vocabulary -> the standing column's values. Phrases
# are matched longest-first ("in repair" before "in …").
_STANDING_PHRASES: tuple[tuple[str, str, str], ...] = (
    ("in repair", "in_repair", "In repair"),
    ("out of service", "broken", "Out of service"),
    ("broken", "broken", "Broken"),
    ("lost", "lost", "Lost"),
    ("stolen", "stolen", "Stolen"),
    ("in service", "in_service", "In service"),
)

_PRICE_RE = re.compile(
    r"\b(under|below|less than|max|up to|over|above|more than|min|at least)\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
_MAX_WORDS = {"under", "below", "less than", "max", "up to"}


def _owner_vocabulary(db: Session, owner_id: uuid.UUID) -> dict:
    tools = service.list_tools(db, owner_id, include_attached=True)
    batteries = service.list_batteries(db, owner_id)
    brands = sorted(
        {t.brand.strip() for t in tools + batteries if t.brand and t.brand.strip()},
        key=len,
        reverse=True,
    )
    categories = sorted(
        {
            t.category.strip()
            for t in tools + batteries
            if t.category and t.category.strip()
        },
        key=len,
        reverse=True,
    )
    locations = sorted(
        {
            t.location.strip()
            for t in tools + batteries
            if t.location and t.location.strip()
        },
        key=len,
        reverse=True,
    )
    tags = service.list_tags(db, owner_id)
    return {
        "brands": brands,
        "categories": categories,
        "locations": locations,
        "tags": tags,
    }


def parse_smart_query(db: Session, owner_id: uuid.UUID, q: str) -> dict:
    text = f" {(q or '').strip()} "
    lowered = text.lower()
    filters: dict = {
        "category": None,
        "location": None,
        "standing": None,
        "tag_id": None,
        "min_price": None,
        "max_price": None,
    }
    chips: list[dict] = []

    def consume(phrase: str) -> bool:
        """Remove the first occurrence of `phrase` (already
        space-padded haystack) — True when it was there."""
        nonlocal text, lowered
        needle = f" {phrase.strip().lower()} "
        idx = lowered.find(needle)
        if idx < 0:
            return False
        text = text[:idx] + " " + text[idx + len(needle) :]
        lowered = text.lower()
        return True

    vocab = _owner_vocabulary(db, owner_id)

    # Prices first — their numbers must not fall into text.
    match = _PRICE_RE.search(text)
    if match:
        word = match.group(1).lower()
        amount = match.group(2).replace(",", "")
        if word in _MAX_WORDS:
            filters["max_price"] = amount
            chips.append({"kind": "price", "label": f"Under ${amount}"})
        else:
            filters["min_price"] = amount
            chips.append({"kind": "price", "label": f"Over ${amount}"})
        text = text[: match.start()] + " " + text[match.end() :]
        lowered = text.lower()

    # Location FIRST: "in <location>" against the owner's own
    # location strings (longest first so "Shop toolbox" beats
    # "Shop") — the owner's literal strings are more specific
    # than the standing vocabulary, so they win the "in …" slot.
    for location in vocab["locations"]:
        if consume(f"in {location}"):
            filters["location"] = location
            chips.append({"kind": "location", "label": f"In {location}"})
            break

    # Standing phrases.
    for phrase, value, label in _STANDING_PHRASES:
        if consume(phrase):
            filters["standing"] = value
            chips.append({"kind": "standing", "label": label})
            break

    # Tag: "tagged <name>" (explicit) wins a slot.
    for tag in vocab["tags"]:
        if consume(f"tagged {tag['name']}"):
            filters["tag_id"] = str(tag["id"])
            chips.append({"kind": "tag", "label": f"Tagged {tag['name']}"})
            break

    # Category + brand: vocabulary phrases still present become
    # chips but STAY in the text too — category text also reads
    # naturally as a search term, and the search endpoints judge
    # category by exact equality, so the exact filter is applied
    # for category; brand has no filter param, so it rides the
    # text query (its phrase is in the search vector).
    for category in vocab["categories"]:
        if f" {category.lower()} " in lowered:
            filters["category"] = category
            chips.append({"kind": "category", "label": f"Category: {category}"})
            break
    for brand in vocab["brands"]:
        if f" {brand.lower()} " in lowered:
            chips.append({"kind": "brand", "label": f"Brand: {brand}"})
            break

    return {"text": " ".join(text.split()), "filters": filters, "chips": chips}
