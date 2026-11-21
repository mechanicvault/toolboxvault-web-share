"""Brand data feeds (sheet row 220) — a maker's own structured
product data, used as an accelerator inside the lookup chain.

Ryan's rule, softened on his word (2026-11-20): where a brand
exposes a clean data feed, the lookup reads the feed first and
the generic browse walk remains the fallback when the feed
fails or lacks a fact. Facts are admitted only from responses
the system actually fetched — the feed is a source the system
opens, held to the same grounding standard as a page read.

Mac Tools first (the brand Ryan directed): mactools.com runs
on Shopify, so every product carries a public JSON twin at
/products/<handle>.json — the variant's retail price, the
product photos, and the maker's own spec tags. Two hard rules
ride every parse:

  - The tags also carry the internal dealer price levels
    ("PRICE:NA2", "PRICE:STP", ...). Those are NEVER read,
    stored or shown — the only price a feed result may carry
    is the variant's retail price.
  - A set's contents come from the maker's own page: the
    product page's "Add items from this set" section embeds
    its SKU list in the page itself, and each piece's facts
    come from that piece's own feed record — a piece the feed
    doesn't know stays a part number with no invented facts.

The layer is operator-gated (settings key
`catalog.feed_mac_enabled`, default off): a brand-new outbound
path ships dark and is lit deliberately, and it can be killed
from settings if a maker ever objects to the traffic. Every
fetch is a plain read of a public endpoint, results land in
the library through the ordinary write-back, so each product
is fetched rarely — the library answers repeat lookups.
"""

import re
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy.orm import Session

from app.modules.catalog import manuals
from app.modules.catalog.normalize import norm_brand, norm_model

MAC_FEED_ENABLED_KEY = "catalog.feed_mac_enabled"

_MAC_BASE = "https://www.mactools.com"
_FEED_TIMEOUT_SECONDS = 10.0
_FEED_MAX_BYTES = 2_000_000
_PAGE_MAX_BYTES = 6_000_000
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_MAX_SET_PIECES = 40
_PIECE_WORKERS = 4

# The EP: spec tags worth keeping (the rest is fulfilment
# bookkeeping). REFINER: tags are the maker's published spec
# facets and are kept whole. PRICE: tags are never touched —
# they are not referenced anywhere in this module's parsing.
_EP_SPEC_LABELS = {
    "CountryOfOrigin": "Country of Origin",
    "Weight": "Weight",
}

_SET_HEADING = "Add items from this set"
_SKUS_RE = re.compile(r'const\s+skus\s*=\s*"([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")


# -- transport (stubbed in tests) ---------------------------------------------


def _fetch_bytes(url: str, max_bytes: int) -> bytes | None:
    """One polite GET of a feed URL we constructed (fixed host,
    https). Returns the body bytes, or None on ANY failure —
    a 404, a 429 throttle, a timeout: the feed layer goes
    quiet and the chain falls back to the walk."""
    try:
        manuals.assert_safe_url(url)
    except manuals.ManualError:
        return None
    try:
        with httpx.Client(
            timeout=_FEED_TIMEOUT_SECONDS,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            with client.stream(
                "GET", url, headers={"User-Agent": _USER_AGENT}
            ) as response:
                if response.status_code != 200:
                    return None
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return None
                    chunks.append(chunk)
    except httpx.HTTPError:
        return None
    return b"".join(chunks)


def _fetch_json(url: str) -> dict | None:
    raw = _fetch_bytes(url, _FEED_MAX_BYTES)
    if raw is None:
        return None
    try:
        import json

        body = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _fetch_text(url: str) -> str | None:
    raw = _fetch_bytes(url, _PAGE_MAX_BYTES)
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace")


# -- the Mac / Shopify parse ----------------------------------------------------


def _handle_candidates(model: str) -> list[str]:
    """Shopify handles are lowercase and dot-free; a dotted
    part number (MUP65.5MMR) lives under a dashed handle.
    Candidates in the order a real catalog uses them."""
    base = (model or "").strip().lower()
    if not base:
        return []
    out: list[str] = []
    if "." in base:
        out.append(base.replace(".", "-"))
    out.append(base)
    if "." in base:
        out.append(base.replace(".", ""))
    return list(dict.fromkeys(out))


def _specs_from_tags(tags: str) -> dict:
    """The maker's spec facets from the product's tag string.
    REFINER: facets are published specs; two EP: facts are
    worth keeping. PRICE: tags are dealer price levels and
    are never read — the parser simply has no branch for
    them, so a dealer price cannot leak into a result."""
    specs: dict[str, str] = {}
    for tag in (tags or "").split(","):
        tag = tag.strip()
        if tag.startswith("REFINER:"):
            label, _, value = tag[len("REFINER:") :].partition("|")
            if label.strip() and value.strip():
                specs[label.strip()] = value.strip()
        elif tag.startswith("EP:"):
            key, _, value = tag[len("EP:") :].partition("|")
            label = _EP_SPEC_LABELS.get(key.strip())
            if label and value.strip():
                specs[label] = value.strip()
    return specs


def _money(value: object) -> float | None:
    try:
        amount = float(str(value))
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _product_fields(payload: dict, model: str) -> dict | None:
    """The grounded-shape pieces of one Shopify product JSON.
    The variant is accepted only when its SKU is the part
    number sought — a handle collision must never borrow a
    stranger's price. The price is the variant's RETAIL
    price; the dealer PRICE: tags are not consulted."""
    product = payload.get("product")
    if not isinstance(product, dict):
        return None
    wanted = norm_model(model)
    variant = None
    for candidate in product.get("variants") or []:
        if isinstance(candidate, dict) and norm_model(
            str(candidate.get("sku") or "")
        ) == wanted:
            variant = candidate
            break
    if variant is None:
        return None
    fields: dict = {"brand": "Mac Tools", "model": model}
    title = str(product.get("title") or "").strip()
    if title:
        fields["name"] = title
    price = _money(variant.get("price"))
    if price is not None:
        fields["msrp"] = price
    body = _TAG_RE.sub(" ", str(product.get("body_html") or ""))
    body = " ".join(body.split())
    if body and body != title and 20 <= len(body) <= 1000:
        fields["description"] = body
    specs = _specs_from_tags(str(product.get("tags") or ""))
    if specs.get("Type"):
        fields["category"] = specs["Type"]
    photos = [
        str(image["src"]).strip()
        for image in product.get("images") or []
        if isinstance(image, dict) and image.get("src")
    ]
    return {
        "fields": fields,
        "specs": specs,
        "photos": photos,
        "image_url": photos[0] if photos else None,
        "handle": str(product.get("handle") or "").strip(),
    }


def _set_skus_from_html(html: str) -> list[str]:
    """The set's own contents list: the SKU list embedded in
    the page's "Add items from this set" section. Anchored to
    the heading so a merely-related list elsewhere on the
    page is never mistaken for the set's contents."""
    anchor = html.find(_SET_HEADING)
    if anchor < 0:
        return []
    match = _SKUS_RE.search(html[anchor : anchor + 60_000])
    if match is None:
        return []
    return [
        sku.strip()
        for sku in match.group(1).split(",")
        if sku.strip()
    ]


def _piece_for_sku(sku: str) -> dict:
    """One set piece from its own feed record: name, retail
    price, photo. A piece the feed doesn't know stays a bare
    part number — the maker's page stated the number, and no
    fact is invented to dress it up."""
    piece = {"name": "", "model": sku, "msrp": None, "image_url": None}
    for handle in _handle_candidates(sku):
        payload = _fetch_json(f"{_MAC_BASE}/products/{handle}.json")
        if payload is None:
            continue
        parsed = _product_fields(payload, sku)
        if parsed is None:
            continue
        piece["name"] = str(parsed["fields"].get("name") or "")
        piece["msrp"] = parsed["fields"].get("msrp")
        piece["image_url"] = parsed["image_url"]
        break
    return piece


def mac_product(model: str, *, quick: bool = False) -> dict | None:
    """The feed's answer for one Mac Tools part number, in the
    grounded result shape — or None when the feed has nothing
    (unknown part, throttled, dark network): the walk decides
    from there, exactly as if the feed didn't exist."""
    candidates = _handle_candidates(model)
    if not candidates:
        return None
    parsed = None
    handle = ""
    for candidate in candidates[: 1 if quick else len(candidates)]:
        payload = _fetch_json(f"{_MAC_BASE}/products/{candidate}.json")
        if payload is None:
            continue
        parsed = _product_fields(payload, model)
        if parsed is not None:
            handle = candidate
            break
    if parsed is None:
        return None
    handle = parsed["handle"] or handle
    source_url = f"{_MAC_BASE}/products/{handle}"
    pieces: list[dict] = []
    html = _fetch_text(source_url)
    if html:
        skus = [
            sku
            for sku in _set_skus_from_html(html)
            if norm_model(sku) != norm_model(model)
        ][:_MAX_SET_PIECES]
        if skus:
            with ThreadPoolExecutor(max_workers=_PIECE_WORKERS) as pool:
                pieces = list(pool.map(_piece_for_sku, skus))
    return {
        "fields": parsed["fields"],
        "pieces": pieces,
        "piece_count": None,
        "photos": parsed["photos"],
        "specs": parsed["specs"],
        "warranty_type": None,
        "warranty_months": None,
        "warranty_terms": None,
        "source_name": "Mac Tools",
        "source_url": source_url,
        "image_url": parsed["image_url"],
        "ai_used": False,
    }


# -- the chain's door -----------------------------------------------------------


def feed_product(
    db: Session, *, brand: str = "", model: str = "", quick: bool = False
) -> dict | None:
    """The feed layer's answer for a lookup, or None. Brand
    dispatch lives here so the chain stays brand-blind; Mac
    Tools is the first feed (row 220's order)."""
    if not model:
        return None
    if norm_brand(brand) == "mac":
        from app.modules.billing import entitlements

        enabled = entitlements.get_setting(db, MAC_FEED_ENABLED_KEY, False)
        if enabled in (True, "true", "True", "1"):
            return mac_product(model, quick=quick)
    return None
