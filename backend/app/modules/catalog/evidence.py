"""The evidence layer (lookup rebuild Phase 1, 2026-11-20).

The agent that replaces the fixed walk may only use facts it
can point at. This module is where those facts live:

- `ResponseRecorder` keeps the JSON responses a rendered
  page downloads (the data behind rotating lists, tabs and
  carousels), scrubbed at the door: no request headers or
  cookies are ever stored, fields named like credentials are
  blanked, and internal PRICE: dealer tags are stripped
  before anything downstream can read them.
- `build_page_map` segments a rendered page into labeled
  sections with their product-card groups and counts, using
  generic signals only (headings, landmarks, keyword-bearing
  ids/classes, repeated card structures) — never a brand's
  layout. The agent reads the map, then reads one section.
- `store_evidence` / `evidence_for` persist observations in
  catalog_evidence, keyed by brand + part number, so a run's
  work is replayable and auditable offline.

Nothing here decides what a section MEANS — labeling is the
agent's job (Phase 3) and proving is the referee's (Phase 2).
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalog import models as catalog_models
from app.modules.catalog.normalize import norm_brand, norm_model

# ----------------------------------------------------------------
# Scrubbing — applied to everything before it is stored or read.
# ----------------------------------------------------------------

_SCRUB_KEY_RE = re.compile(
    r"token|session|auth|cart|e-?mail|passwd|password|secret|cookie",
    re.IGNORECASE,
)
_PRICE_TAG_RE = re.compile(r"PRICE:\s*[^\s\",;]+")
_MAX_STRING = 4_000


def scrub(value):
    """A scrubbed deep copy of a JSON value: credential-named
    fields blanked, internal PRICE: tags cut out of strings,
    overlong strings trimmed. Response bodies only — headers
    and cookies are never passed here in the first place."""
    if isinstance(value, dict):
        return {
            key: ("[scrubbed]" if _SCRUB_KEY_RE.search(str(key)) else scrub(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        cleaned = _PRICE_TAG_RE.sub("", value)
        return cleaned[:_MAX_STRING]
    return value


# ----------------------------------------------------------------
# Recorded data responses.
# ----------------------------------------------------------------

_MAX_RESPONSE_BYTES = 2_000_000
_MAX_RECORDINGS = 40
_MAX_ARRAYS = 24


def summarize_payload(data) -> list[dict]:
    """The arrays inside a JSON payload, largest first: path,
    item count, and the field names of a sample item — the
    summary an agent scans to find the response holding a
    set's piece list."""
    found: list[dict] = []
    stack: list[tuple[str, object]] = [("$", data)]
    while stack and len(found) < _MAX_ARRAYS:
        path, node = stack.pop()
        if isinstance(node, list):
            if len(node) >= 2 and isinstance(node[0], dict):
                found.append(
                    {
                        "path": path,
                        "count": len(node),
                        "keys": sorted(str(k) for k in node[0].keys())[:16],
                    }
                )
            for index, item in enumerate(node[:3]):
                if isinstance(item, (dict, list)):
                    stack.append((f"{path}[{index}]", item))
        elif isinstance(node, dict):
            for key, item in node.items():
                if isinstance(item, (dict, list)):
                    stack.append((f"{path}.{key}", item))
    found.sort(key=lambda entry: -entry["count"])
    return found[:_MAX_ARRAYS]


class ResponseRecorder:
    """Collects a rendered page's JSON responses. Bodies are
    parsed, scrubbed and summarized as they arrive; anything
    non-JSON, oversized, or past the cap is skipped."""

    def __init__(self) -> None:
        self.recordings: list[dict] = []

    def offer(self, url: str, status: int, content_type: str, body: str) -> None:
        if len(self.recordings) >= _MAX_RECORDINGS:
            return
        if "json" not in (content_type or "").lower():
            return
        if not body or len(body.encode("utf-8", "replace")) > _MAX_RESPONSE_BYTES:
            return
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return
        data = scrub(data)
        self.recordings.append(
            {
                "url": url[:1_000],
                "status": status,
                "arrays": summarize_payload(data),
                "data": data,
            }
        )

    def summaries(self) -> list[dict]:
        return [
            {
                "url": rec["url"],
                "status": rec["status"],
                "arrays": rec["arrays"],
            }
            for rec in self.recordings
        ]

    def data_at(self, url: str, path: str):
        """The recorded payload (or the array at a `$...` path
        inside it) for one response — the agent's read of a
        data response, e.g. the 24-item list behind a tab."""
        for rec in self.recordings:
            if rec["url"] != url:
                continue
            node = rec["data"]
            if path and path != "$":
                for part in re.findall(r"\.([^.\[\]]+)|\[(\d+)\]", path):
                    key, index = part
                    try:
                        node = node[key] if key else node[int(index)]
                    except (KeyError, IndexError, TypeError):
                        return None
            return node
        return None


# ----------------------------------------------------------------
# The page map — generic segmentation of a rendered page.
# ----------------------------------------------------------------

_SECTION_KEYWORDS = (
    "set details",
    "set contents",
    "contents",
    "includes",
    "included",
    "what's in the box",
    "whats in the box",
    "in the box",
    "details",
    "specifications",
    "similar",
    "related",
    "recommended",
    "you may also",
    "customers also",
    "also bought",
    "accessories",
    "add-ons",
    "addons",
)
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4"}
_MAX_MAP_SECTIONS = 40
_MAX_SAMPLES = 6


class _Node:
    __slots__ = ("tag", "attrs", "children", "text_parts", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Node] = []
        self.text_parts: list[str] = []
        self.parent = parent

    def text(self) -> str:
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.text())
        return " ".join(" ".join(parts).split())


class _DomBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {}, None)
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1].children.append(
            _Node(tag, dict(attrs), self._stack[-1])
        )

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                break

    def handle_data(self, data):
        if data.strip():
            self._stack[-1].text_parts.append(data.strip())


def _keyword_of(node: _Node, heading: str) -> str | None:
    """The first section keyword this container announces —
    in its heading text, id, class, or aria-label. Generic
    vocabulary, never a site's own class names."""
    haystacks = [
        heading.lower(),
        (node.attrs.get("id") or "").lower().replace("-", " ").replace("_", " "),
        (node.attrs.get("class") or "").lower().replace("-", " ").replace("_", " "),
        (node.attrs.get("aria-label") or "").lower(),
    ]
    for haystack in haystacks:
        for keyword in _SECTION_KEYWORDS:
            if keyword in haystack:
                return keyword
    return None


def _has_link(node: _Node) -> bool:
    stack = [node]
    while stack:
        current = stack.pop()
        if current.tag == "a" and current.attrs.get("href"):
            return True
        stack.extend(current.children)
    return False


def _card_children(node: _Node) -> list[_Node]:
    """The section's cards: the leaf-most elements that hold
    a link and a readable amount of text — the generic shape
    of a product or piece card, whether the cards sit directly
    in the section or inside a grid container within it."""
    descendants: list[_Node] = []

    def collect(current: _Node) -> None:
        for child in current.children:
            if child.tag in ("script", "style"):
                continue
            descendants.append(child)
            collect(child)

    collect(node)

    def qualifies(candidate: _Node) -> bool:
        return (
            candidate.tag != "a"
            and len(candidate.text()) >= 10
            and _has_link(candidate)
        )

    return [
        candidate
        for candidate in descendants
        if qualifies(candidate)
        and not any(qualifies(child) for child in candidate.children)
    ]


def _heading_path(node: _Node) -> list[str]:
    path = []
    current = node.parent
    while current is not None and len(path) < 4:
        for child in current.children:
            if child.tag in _HEADING_TAGS and child.text():
                path.append(child.text()[:80])
                break
        current = current.parent
    return list(reversed(path))


def build_page_map(html: str, recordings: list[dict] | None = None) -> dict:
    """Segment a rendered page for the agent: title, stated
    piece count, embedded structured products, the labeled
    sections with their card groups, and the recorded data
    responses. Samples are scrubbed like everything else."""
    builder = _DomBuilder()
    builder.feed(html or "")
    root = builder.root

    title = ""
    stated_count = None
    jsonld_products: list[dict] = []
    sections: list[dict] = []

    # Aside is deliberately NOT chrome here: a cross-sell rail
    # inside the content is a section the referee must see
    # labeled (similar / related), or it cannot drop its items.
    _CHROME_TAGS = {"header", "nav", "footer"}
    _CHROME_ROLES = {"navigation", "banner", "contentinfo", "search", "menubar"}

    def walk(node: _Node, depth: int, in_chrome: bool = False) -> None:
        nonlocal title, stated_count
        if node.tag in _CHROME_TAGS or (
            (node.attrs.get("role") or "").lower() in _CHROME_ROLES
        ):
            # Page chrome — menus, banners, footers — is never a
            # content section. Without this the map fills with
            # mega-menu "sections" and the product's own panels
            # drown (live evidence, 2026-11-20: a Mac set's map
            # was eight navigation menus).
            in_chrome = True
        if node.tag == "title" and not title:
            title = node.text()[:200]
        if node.tag in _HEADING_TAGS and stated_count is None:
            from app.modules.catalog.grounded import detect_piece_count

            stated_count = detect_piece_count(node.text())
        if node.tag == "script" and (
            node.attrs.get("type") or ""
        ).lower() == "application/ld+json":
            try:
                data = json.loads(node.text())
            except (ValueError, TypeError):
                data = None
            if isinstance(data, dict) and data.get("@type") == "Product":
                jsonld_products.append(
                    {
                        "name": scrub(str(data.get("name") or ""))[:200],
                        "sku": scrub(str(data.get("sku") or ""))[:120],
                        "has_price": bool(data.get("offers")),
                        "has_image": bool(data.get("image")),
                    }
                )
        if not in_chrome and depth < 14 and len(sections) < _MAX_MAP_SECTIONS:
            heading = ""
            for child in node.children:
                if child.tag in _HEADING_TAGS and child.text():
                    heading = child.text()[:120]
                    break
            keyword = _keyword_of(node, heading)
            cards = _card_children(node)
            if keyword is not None and len(cards) >= 1:
                sections.append(
                    {
                        "heading": heading,
                        "heading_path": _heading_path(node),
                        "keyword": keyword,
                        "card_count": len(cards),
                        "samples": [
                            scrub(card.text())[:200]
                            for card in cards[:_MAX_SAMPLES]
                        ],
                    }
                )
        for child in node.children:
            walk(child, depth + 1, in_chrome)

    walk(root, 0)
    if stated_count is None and title:
        from app.modules.catalog.grounded import detect_piece_count

        stated_count = detect_piece_count(title)
    return {
        "title": scrub(title),
        "stated_piece_count": stated_count,
        "jsonld_products": jsonld_products,
        "sections": sections,
        "data_responses": list(recordings or []),
    }


# ----------------------------------------------------------------
# Storage — every observation, keyed by brand + part number.
# ----------------------------------------------------------------


def store_evidence(
    db: Session,
    *,
    brand: str,
    model: str,
    url: str,
    kind: str,
    section: str | None,
    payload: dict,
) -> None:
    """Persist one observation. Bookkeeping next to the
    lookup: callers treat failures as non-fatal."""
    db.add(
        catalog_models.CatalogEvidence(
            brand_key=norm_brand(brand),
            model_key=norm_model(model),
            url=url[:1000],
            kind=kind[:40],
            section=(section or None) and section[:400],
            payload=payload,
        )
    )
    db.commit()


def evidence_for(db: Session, *, brand: str, model: str) -> list[dict]:
    rows = db.scalars(
        select(catalog_models.CatalogEvidence)
        .where(
            catalog_models.CatalogEvidence.brand_key == norm_brand(brand),
            catalog_models.CatalogEvidence.model_key == norm_model(model),
        )
        .order_by(catalog_models.CatalogEvidence.created_at)
    ).all()
    return [
        {
            "url": row.url,
            "kind": row.kind,
            "section": row.section,
            "payload": row.payload,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
