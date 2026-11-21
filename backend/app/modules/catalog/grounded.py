"""Grounded web lookup — the pipe that
lets the lookup chain answer from a REAL product page instead of
the AI's memory.

Why this exists: the Lookup Truth Audit proved the text-only AI
seam cannot know tool-truck SKUs (Matco SPRB4A came back 0-for-21
— echoes, inventions, and a different answer per retry), and even
a famous DeWalt SKU was recalled with false specs (a 1/4-inch
"impact driver" for the 1/2-inch DCF891 impact wrench). The facts
live on the manufacturer's / retailer's product page. This module
fetches that page and reads the facts OFF it:

  1. SEARCH (the AI provider's own web search, through the
     billing AI seam — the owner's one-vendor decision,
     2026-10-25; the manual finder rides the same door) finds
     candidate product pages for brand+model. Only the search's
     citation URLs cross into this pipe — its answer text is
     never evidence. A user-pasted product link skips the
     search entirely.
  2. FETCH is SSRF-guarded exactly like manual downloads (https
     only, every redirect hop re-validated, no private hosts).
  3. EXTRACT works in two passes over the fetched page ONLY:
     deterministic structured data first (JSON-LD Product blocks
     and embedded product records like a store's page payload —
     page-supported by construction), then the AI seam reads the
     page's own text for the gaps — and every AI-proposed value
     must be SUPPORTED by the page text (its tokens appear there)
     or it is dropped. The AI never contributes a fact the page
     doesn't state.
  4. The result names its source (the page it came from) and can
     carry the page's real product photo — never an invented URL.

Nothing here charges credits; the chain (catalog.lookup) meters
the AI extraction through the usual lookup action, exactly like
the AI-only layer it supplements.
"""

import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.storage import (
    ALLOWED_CONTENT_TYPES,
    content_matches_declared,
    storage,
)
from app.modules.billing import ai_service
from app.modules.catalog import manuals
from app.modules.catalog.normalize import canonical_brand, norm_text

_FIELDS = (
    "name",
    "brand",
    "model",
    "category",
    "size",
    "msrp",
    "description",
    # Row 199: the lookup pulls everything the page states that
    # the system has a field for — the barcode included.
    "upc",
)

_FETCH_TIMEOUT_SECONDS = 20.0
_PAGE_MAX_BYTES = 6_000_000
_PHOTO_MAX_BYTES = 10_000_000
_TEXT_CAP = 60_000
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class PageFetchError(ValueError):
    """The page couldn't be read — the surfaces turn this into a
    plain "couldn't read that page" outcome, never a guess."""


# -- URL safety ---------------------------------------------------------------


def validate_page_url(url: str) -> str:
    """Shape + SSRF gate for a user-supplied product link: https,
    a real public host, no credentials in the URL. Returns the
    cleaned URL or raises PageFetchError with plain copy."""
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PageFetchError("That link doesn't look like a web page address.")
    if parsed.username or parsed.password:
        raise PageFetchError("That link doesn't look like a web page address.")
    try:
        manuals.assert_safe_url(cleaned)
    except manuals.ManualError as exc:
        raise PageFetchError(str(exc)) from exc
    return cleaned


# -- fetching -----------------------------------------------------------------


def _fetch_html(url: str) -> str:
    """GET one page's HTML with the manual-download guards:
    https only, every redirect hop re-validated against the
    SSRF rules, a size cap, and an HTML content requirement.
    (The transport seam — tests stub this one function.)
    Raises PageFetchError on any failure."""
    current = url
    # trust_env=False is load-bearing (see manuals._download):
    # an env proxy would resolve DNS itself and silently defeat
    # the SSRF guard, which judges the addresses WE resolve.
    with httpx.Client(
        timeout=_FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for _hop in range(manuals.MAX_REDIRECTS + 1):
            try:
                manuals.assert_safe_url(current)
            except manuals.ManualError as exc:
                raise PageFetchError(str(exc)) from exc
            try:
                with client.stream(
                    "GET", current, headers={"User-Agent": _USER_AGENT}
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise PageFetchError(
                                "That page sent us elsewhere and stopped."
                            )
                        current = str(httpx.URL(current).join(location))
                        continue
                    if response.status_code != 200:
                        raise PageFetchError(
                            f"That page answered HTTP {response.status_code}."
                        )
                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";")[0]
                        .strip()
                        .lower()
                    )
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > _PAGE_MAX_BYTES:
                            raise PageFetchError("That page is too large to read.")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
            except httpx.HTTPError as exc:
                raise PageFetchError("Couldn't reach that page.") from exc
            if content_type not in ("text/html", "application/xhtml+xml", ""):
                raise PageFetchError("That link didn't lead to a web page.")
            head = raw[:512].lower()
            if content_type == "" and b"<html" not in head and b"<!doctype" not in head:
                raise PageFetchError("That link didn't lead to a web page.")
            charset = "utf-8"
            match = re.search(rb'charset=["\']?([\w-]+)', raw[:2048], re.I)
            if match:
                charset = match.group(1).decode("ascii", "replace")
            try:
                return raw.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                return raw.decode("utf-8", errors="replace")
    raise PageFetchError("That page redirected too many times.")


# -- page parsing ---------------------------------------------------------------


class _PageParser(HTMLParser):
    """One pass over the HTML collecting everything extraction
    may use: title, meta (og/twitter), JSON-LD blocks, the
    __NEXT_DATA__ payload some stores embed, visible text, and
    image candidates. Script/style content never reaches the
    visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.jsonld: list[str] = []
        self.next_data: str = ""
        self.text_parts: list[str] = []
        self.images: list[dict] = []
        self.links: list[str] = []
        self._in_title = False
        self._title_seen = False
        self._script_kind: str | None = None  # "jsonld" | "next" | "other"
        self._script_parts: list[str] = []
        self._hidden_depth = 0  # inside style/noscript/template/svg

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            # Only the page's own (first, non-hidden) title —
            # inline SVG icons carry their own <title> children
            # ("User", "Arrow left", …) that would otherwise be
            # glued onto the product name.
            if not self._hidden_depth and not self._title_seen:
                self._in_title = True
                self._title_seen = True
        elif tag == "meta":
            key = (attr.get("property") or attr.get("name") or "").lower()
            if key and attr.get("content"):
                self.meta.setdefault(key, attr["content"])
        elif tag == "script":
            kind = "other"
            if attr.get("type", "").lower() == "application/ld+json":
                kind = "jsonld"
            elif attr.get("id") == "__NEXT_DATA__":
                kind = "next"
            self._script_kind = kind
            self._script_parts = []
        elif tag in ("style", "noscript", "template", "svg"):
            self._hidden_depth += 1
        elif tag == "img":
            src = attr.get("src") or attr.get("data-src") or ""
            if src:
                self.images.append(
                    {
                        "src": src,
                        "width": attr.get("width", ""),
                        "height": attr.get("height", ""),
                        "alt": attr.get("alt", ""),
                    }
                )
        elif tag == "a":
            href = attr.get("href", "")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._script_kind is not None:
            body = "".join(self._script_parts)
            if self._script_kind == "jsonld":
                self.jsonld.append(body)
            elif self._script_kind == "next":
                self.next_data = body
            self._script_kind = None
            self._script_parts = []
        elif tag in ("style", "noscript", "template", "svg") and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._script_kind is not None:
            self._script_parts.append(data)
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._hidden_depth:
            return
        text = data.strip()
        if text:
            self.text_parts.append(text)


def _money(value: object) -> float | None:
    """A price out of whatever shape the page used: a number, a
    "$64.95" string, or a nested {price: ...} / list of offers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d[\d,]*(?:\.\d{1,2})?", value)
        if match:
            try:
                return float(match.group(0).replace(",", ""))
            except ValueError:
                return None
        return None
    if isinstance(value, list):
        for item in value:
            found = _money(item)
            if found is not None:
                return found
    if isinstance(value, dict):
        for key in ("price", "effectivePrice", "value"):
            if key in value:
                found = _money(value[key])
                if found is not None:
                    return found
        for key in ("listPrice", "salePrice", "offers", "priceSpecification"):
            if key in value:
                found = _money(value[key])
                if found is not None:
                    return found
    return None


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "@id"):
            if isinstance(value.get(key), str):
                return value[key].strip()
    return ""


def _image_of(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            found = _image_of(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("largeImg", "url", "contentUrl", "@id"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
        media = value.get("media")
        if isinstance(media, dict):
            found = _image_of(media)
            if found:
                return found
    return ""


def _images_of(value: object) -> list[str]:
    """Every image URL a structured record offers (row 199: the
    lookup takes the page's whole gallery, not just the first
    photo)."""
    out: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            if node.strip() and node.strip() not in out:
                out.append(node.strip())
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key in ("largeImg", "url", "contentUrl", "@id"):
                if isinstance(node.get(key), str):
                    walk(node[key])
            media = node.get("media")
            if isinstance(media, dict):
                walk(media)

    walk(value)
    return out[:8]


def _specs_of(raw: dict) -> dict:
    """The page's specification pairs (schema.org
    additionalProperty), name -> value, as written."""
    out: dict = {}
    props = raw.get("additionalProperty")
    if isinstance(props, dict):
        props = [props]
    if isinstance(props, list):
        for prop in props:
            if not isinstance(prop, dict):
                continue
            name = _as_text(prop.get("name"))
            value = prop.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = str(value)
            value = _as_text(value)
            if name and value and len(name) <= 80 and len(value) <= 200:
                out[name] = value
            if len(out) >= 20:
                break
    return out


def _upc_of(raw: dict) -> str:
    """The product's barcode (GTIN/UPC) from structured data:
    digits only, a plausible barcode length."""
    for key in ("gtin13", "gtin", "gtin14", "gtin12", "gtin8", "upc", "ean"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(int(value))
        if isinstance(value, str):
            digits = re.sub(r"\D", "", value)
            if 8 <= len(digits) <= 14:
                return digits
    return ""


_WARRANTY_YEARS_RE = re.compile(r"(\d{1,3})\s*(?:years?|yrs?)\b", re.IGNORECASE)
_WARRANTY_MONTHS_RE = re.compile(r"(\d{1,4})\s*months?\b", re.IGNORECASE)


def _warranty_from_text(text: str) -> dict:
    """The warranty a page states, in the system's shape:
    warranty_type (term | lifetime | limited), warranty_months
    for a stated term, warranty_terms the words as written
    (a short window around the word "warranty")."""
    if not text or "warranty" not in text.lower():
        return {}
    lowered = text.lower()
    index = lowered.find("warranty")
    window = text[max(0, index - 60) : index + 120]
    window = " ".join(window.split())
    out: dict = {"warranty_terms": window[:200]}
    if "lifetime" in lowered:
        out["warranty_type"] = "lifetime"
        return out
    years = _WARRANTY_YEARS_RE.search(window) or _WARRANTY_YEARS_RE.search(text)
    if years:
        out["warranty_type"] = "term"
        out["warranty_months"] = int(years.group(1)) * 12
        return out
    months = _WARRANTY_MONTHS_RE.search(window) or _WARRANTY_MONTHS_RE.search(text)
    if months:
        out["warranty_type"] = "term"
        out["warranty_months"] = int(months.group(1))
        return out
    out["warranty_type"] = "limited"
    return out


def _normalize_product(raw: dict) -> dict:
    """One structured product record, whatever dialect the page
    spoke, down to the chain's field names."""
    out: dict = {}
    name = _as_text(raw.get("name")) or _as_text(raw.get("displayName"))
    if name:
        out["name"] = name
    brand = _as_text(raw.get("brand")) or _as_text(raw.get("manufacturer"))
    if brand:
        # A maker's structured data may carry its manufacturer
        # CODE ("DW") instead of the brand name — resolve it at
        # this boundary so no consumer ever shows the code (C-08).
        out["brand"] = canonical_brand(brand)
    for key in ("model", "modelCode", "mpn", "sku", "skuId", "partNumber"):
        model = _as_text(raw.get(key))
        if model:
            out["model"] = model
            break
    category = _as_text(raw.get("category"))
    if category:
        out["category"] = category.split(">")[-1].strip()
    # The product description:
    # the page's own words for what the item is. Tag-stripped and
    # length-bounded — a real product sentence, never nav chrome
    # or a whole page dumped into one field. The wizard homes it
    # in the item's Notes, where the user edits it before saving.
    description = _as_text(raw.get("description"))
    if description:
        description = " ".join(re.sub(r"<[^>]+>", " ", description).split())
        if 20 <= len(description) <= 2000:
            out["description"] = description
    price = _money(raw.get("offers")) if "offers" in raw else None
    if price is None:
        price = _money(raw.get("price"))
    if price is None and isinstance(raw.get("skus"), dict):
        for sku in raw["skus"].values():
            if isinstance(sku, dict):
                details = sku.get("skuDetails") or {}
                price = _money(details.get("price"))
                if price is not None:
                    break
    if price is not None:
        out["msrp"] = price
    image = _image_of(raw.get("image")) or _image_of(raw)
    if not image and isinstance(raw.get("skus"), dict):
        for sku in raw["skus"].values():
            if isinstance(sku, dict):
                image = _image_of(sku)
                if image:
                    break
    if image:
        out["image"] = image
    # Row 199: the whole gallery + the barcode + the spec pairs,
    # when the record carries them.
    images = _images_of(raw.get("image"))
    if not images and image:
        images = [image]
    if images:
        out["images"] = images
    upc = _upc_of(raw)
    if upc:
        out["upc"] = upc
    specs = _specs_of(raw)
    if specs:
        out["specs"] = specs
    # Row 195: a set's contents, when the page's structured data
    # lists them (hasPart / isComposedOf) — each piece normalized
    # like the product itself. Page-supported by construction.
    pieces = _normalize_pieces(raw)
    if pieces:
        out["pieces"] = pieces
    return out


def _normalize_piece(raw: object) -> dict | None:
    """One piece of a set, from a structured sub-record."""
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    name = _as_text(raw.get("name")) or _as_text(raw.get("displayName"))
    if name:
        out["name"] = name
    for key in ("model", "modelCode", "mpn", "sku", "skuId", "partNumber"):
        model = _as_text(raw.get(key))
        if model:
            out["model"] = model
            break
    price = _money(raw.get("offers")) if "offers" in raw else None
    if price is None:
        price = _money(raw.get("price"))
    if price is not None:
        out["msrp"] = price
    image = _image_of(raw.get("image")) or _image_of(raw)
    if image:
        out["image_url"] = image
    if not (out.get("name") or out.get("model")):
        return None
    return out


def _normalize_pieces(raw: dict) -> list[dict]:
    for key in ("hasPart", "isComposedOf"):
        parts = raw.get(key)
        if isinstance(parts, dict):
            parts = [parts]
        if isinstance(parts, list):
            pieces = [
                piece
                for piece in (_normalize_piece(part) for part in parts)
                if piece
            ]
            if pieces:
                return pieces[:64]
    return []


def _jsonld_products(blocks: list[str]) -> list[dict]:
    out: list[dict] = []
    for block in blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                kind = node.get("@type")
                kinds = kind if isinstance(kind, list) else [kind]
                if "Product" in kinds:
                    product = _normalize_product(node)
                    if product.get("name"):
                        out.append(product)
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return out


_NAME_KEYS = ("name", "displayName", "title")
_MODEL_KEYS = ("model", "modelCode", "mpn", "sku", "skuId", "partNumber")


def _embedded_products(payload: str) -> list[dict]:
    """Product records embedded in a store's page payload (the
    __NEXT_DATA__ pattern): a record counts when it carries BOTH
    a product name and a model/SKU key — the two together are
    what make it a product and not a navigation entry."""
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except ValueError:
        return []
    out: list[dict] = []
    seen = 0
    stack = [data]
    # The budget must cover the whole payload: real store pages
    # bury the product record behind enormous navigation and
    # category trees (Matco's is ~30k nodes before the product),
    # and a shallow cap silently reads the page as product-less.
    # The fetch cap (6 MB) bounds the worst case.
    while stack and seen < 250_000:
        node = stack.pop()
        seen += 1
        if isinstance(node, dict):
            has_name = any(
                isinstance(node.get(k), str) and node[k].strip() for k in _NAME_KEYS
            )
            has_model = any(
                isinstance(node.get(k), str) and node[k].strip() for k in _MODEL_KEYS
            )
            if has_name and has_model:
                product = _normalize_product(node)
                if product.get("name") and product.get("model"):
                    out.append(product)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def parse_page(html: str, url: str, media: list | None = None) -> dict:
    """Parse fetched HTML into the extraction bundle: title,
    visible text, structured product records, the page's main
    image, and the normalized evidence every claimed fact is
    checked against. `media` is the rendered loader's photo
    inventory (row 200): each photo on the loaded page with
    the text of the card around it — the pairing source for
    set-piece photos."""
    parser = _PageParser()
    try:
        parser.feed(html)
    except Exception:
        # A malformed page still yields whatever was collected;
        # extraction decides whether any of it is usable.
        pass
    title = " ".join(" ".join(parser.title_parts).split())
    if not title:
        title = parser.meta.get("og:title", "")
    text = "\n".join(parser.text_parts)[:_TEXT_CAP]
    structured = _jsonld_products(parser.jsonld)
    embedded = _embedded_products(parser.next_data)
    candidates = structured + embedded

    image_url = ""
    for candidate in candidates:
        if candidate.get("image"):
            image_url = candidate["image"]
            break
    if not image_url:
        image_url = parser.meta.get("og:image") or parser.meta.get(
            "twitter:image", ""
        )
    if image_url:
        image_url = urljoin(url, image_url)
        if not image_url.startswith("https://"):
            image_url = ""
    # Row 199: every photo the page offers for this product —
    # the chosen records' galleries first, the headline photo
    # folded in — resolved absolute, https only, de-duplicated.
    images: list[str] = []
    for candidate in candidates:
        for raw_image in candidate.get("images") or []:
            absolute = urljoin(url, raw_image)
            if absolute.startswith("https://") and absolute not in images:
                images.append(absolute)
        if len(images) >= 8:
            break
    if image_url and image_url not in images:
        images.insert(0, image_url)
    # Row 200: the rendered loader's photo inventory joins the
    # pool — on a script-built page the gallery lives in the
    # loaded DOM, not in structured records. Cleaned here like
    # every other URL the page offers: absolute, https only.
    clean_media: list[dict] = []
    for entry in media or []:
        if not isinstance(entry, dict):
            continue
        src = urljoin(url, str(entry.get("src") or ""))
        if not src.startswith("https://"):
            continue
        if any(item["src"] == src for item in clean_media):
            continue
        clean_media.append(
            {
                "src": src,
                "alt": str(entry.get("alt") or "")[:120],
                "context": str(entry.get("context") or "")[:160],
            }
        )
        # The loader already drops page chrome and puts the
        # main content first; the inventory keeps everything
        # it is given (the row 200 fix: a 40 cap here silently
        # cut a set's piece photos, which sit deep in the list).
        if len(clean_media) >= 200:
            break
    for item in clean_media:
        if item["src"] not in images:
            images.append(item["src"])
    images = images[:8]
    host = urlparse(url).hostname or ""
    # Absolute page links, for the one hop the search walk may
    # take off a listing page toward the product page it lists.
    links: list[str] = []
    for href in parser.links:
        absolute = urljoin(url, href)
        if absolute.startswith("https://") and absolute not in links:
            links.append(absolute)
        if len(links) >= 300:
            break
    evidence = norm_text(
        " ".join(
            [
                title,
                parser.meta.get("og:title", ""),
                parser.meta.get("description", ""),
                json.dumps(candidates)[:8000],
                text,
            ]
        )
    )
    return {
        "url": url,
        "host": host,
        "site_name": parser.meta.get("og:site_name", "") or host,
        "title": title,
        "text": text,
        "candidates": candidates,
        "image_url": image_url,
        "images": images,
        "media": clean_media,
        "links": links,
        "evidence": evidence,
        "evidence_tokens": set(evidence.split()),
        # The page's own one-line summary of itself (og /
        # meta description): the deterministic description
        # fallback when the structured product record carries
        # none — the page describing its product in its own
        # words is page-supported by construction.
        "meta_description": (
            parser.meta.get("og:description", "")
            or parser.meta.get("description", "")
        ),
    }


# Row 200: the markers of a script-built application shell —
# framework mount points and data islands whose product
# content only exists after the page's scripts run. Generic
# framework shapes, never anything site-specific.
_SHELL_MARKERS = (
    'id="__next"',
    "id='__next'",
    'id="root"',
    'id="app"',
    "data-reactroot",
    "ng-version",
    "__next_data__",
)


def _set_contents_missing(page: dict) -> bool:
    """True when the page presents a set (its name or title
    says so, or a piece count is stated) but the parse
    carries none of its pieces — the contents live in the
    loaded page's tabs and cards, not in the download."""
    if any(candidate.get("pieces") for candidate in page["candidates"]):
        return False
    names = [str(c.get("name") or "") for c in page["candidates"]]
    names.append(str(page.get("title") or ""))
    return any(
        _SET_WORD_RE.search(name)
        or detect_piece_count(name, "", str(page.get("title") or ""))
        for name in names
    )


def _looks_like_shell(html: str, page: dict) -> bool:
    """True when the raw download is an application shell: no
    structured product record at all, or a framework shell
    whose visible text is a stub. Such a page can only be
    read by loading it in a browser."""
    if not page["candidates"]:
        return True
    lowered = html.lower()
    if any(marker in lowered for marker in _SHELL_MARKERS):
        if len(page["text"]) < 4000:
            return True
        # Row 200 fix, third round: a script-built set page
        # can carry its product record in a data island (so
        # the download parses, fields and all) while the
        # set's contents exist only once the page loads.
        # When the download shows a set but none of its
        # pieces, the browser read is still owed.
        return _set_contents_missing(page)
    return False


def _parse_richness(page: dict) -> tuple[int, int]:
    """Which of two parses of the same page carries more:
    structured product records first, then readable text."""
    return (len(page["candidates"]), len(page["text"]))


def fetch_product_page(url: str, *, allow_render: bool = True) -> dict:
    """Validate + fetch + parse one product page. Raises
    PageFetchError when the page can't be read.

    Row 200: the raw download is read first; when it is an
    application shell, the page is also loaded in the
    server-side browser (catalog.rendered) and the richer of
    the two readings is used — a script-built page's tabs,
    galleries and set lists exist only in the loaded page.
    A browser failure falls back to the raw reading: the
    lookup never gets worse than the download alone.

    Row 203: the QUICK lookup passes allow_render=False —
    the browser read is the slow part, and the quick pass
    exists to hand back the basic facts in seconds. The
    full-information import runs the same page again with
    the browser allowed."""
    cleaned = validate_page_url(url)
    html = _fetch_html(cleaned)
    page = parse_page(html, cleaned)
    if not allow_render or not _looks_like_shell(html, page):
        return page
    from . import rendered

    if not rendered.rendered_enabled():
        return page
    try:
        dom_html, media = rendered.render_page(cleaned)
    except rendered.RenderError:
        return page
    rendered_page = parse_page(dom_html, cleaned, media=media)
    if _parse_richness(rendered_page) > _parse_richness(page):
        return rendered_page
    return page


# -- support validation ---------------------------------------------------------


def value_supported(value: object, page: dict) -> bool:
    """True when the page actually supports this value: most of
    its meaningful tokens appear in the page evidence. This is
    the mechanical half of "extract ONLY from the page" — the
    prompt says it, this check enforces it."""
    if not isinstance(value, str) or not value.strip():
        return False
    tokens = [
        token
        for token in norm_text(value).split()
        if len(token) >= 3 or any(ch.isdigit() for ch in token)
    ]
    if not tokens:
        return False
    evidence_tokens: set = page["evidence_tokens"]
    present = sum(1 for token in tokens if token in evidence_tokens)
    return present / len(tokens) >= 0.7


def money_supported(value: object, page: dict) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    amount = float(value)
    evidence = page["evidence"]
    forms = {
        f"{amount:.2f}",
        f"{amount:.0f}" if amount == int(amount) else "",
        f"{amount:,.2f}",
        # The evidence is norm_text output, where "$11.99" on the
        # page reads "11 99" (punctuation became spaces) — without
        # this form no price with cents could ever validate.
        f"{amount:.2f}".replace(".", " "),
        f"{amount:,.2f}".replace(".", " "),
    }
    return any(form and form in evidence for form in forms)


def count_supported(count: int, page: dict) -> bool:
    """True when the page ties this number to drawers ("13
    drawers", "13-drawer", "Drawers: 13", a "| 13 | Drawers |"
    table cell once tags are stripped)."""
    evidence = page["evidence"]
    patterns = (
        rf"\b{count}\s+drawers?\b",
        rf"\b{count}\s+drawer\b",
        rf"\bdrawers?\s+{count}\b",
    )
    return any(re.search(pattern, evidence) for pattern in patterns)


# -- set contents (row 195) ------------------------------------------------------

_PIECE_COUNT_RE = re.compile(r"\b(\d{1,3})\s*-?\s*(?:pieces?|pcs?)\b", re.IGNORECASE)
_SET_WORD_RE = re.compile(r"\b(?:set|kit)\b", re.IGNORECASE)


def detect_piece_count(*texts: str) -> int | None:
    """The piece count a string states ("13-Piece", "13 pc",
    "13pcs"), or None. Only counts of 2+ describe a set."""
    for text in texts:
        if not text:
            continue
        match = _PIECE_COUNT_RE.search(text)
        if match:
            count = int(match.group(1))
            if 2 <= count <= 500:
                return count
    return None


def piece_count_supported(count: int, page: dict) -> bool:
    """True when the page evidence ties this number to pieces
    (evidence is norm_text: punctuation already became spaces,
    so "13-piece" reads "13 piece"; the glued "13pc" form is
    checked too)."""
    evidence = page["evidence"]
    patterns = (
        rf"\b{count}\s+pieces?\b",
        rf"\b{count}\s+pcs?\b",
        rf"\b{count}(?:pieces?|pcs?)\b",
    )
    return any(re.search(pattern, evidence) for pattern in patterns)


_CODE_TOKEN_RE = re.compile(r"[a-z]*\d[a-z0-9]{3,}")


def _piece_photo_supported(piece: dict, image_url: str, page: dict) -> bool:
    """Row 200: an AI-proposed piece photo survives only when
    the page's own photo inventory carries that exact photo
    AND the text around the photo (its card / caption / alt)
    supports this piece — its part number, or most of its
    name. A photo the page shows for something else never
    attaches to a piece: when the card names a part number,
    that number owns the photo — a shared product name ("Torx
    Bit Socket" is every piece in the set) can't claim it."""
    media = page.get("media") or []
    entry = next((m for m in media if m.get("src") == image_url), None)
    if entry is None:
        return False
    around = norm_text(f"{entry.get('alt', '')} {entry.get('context', '')}")
    if not around:
        return False
    model = norm_text(piece.get("model") or "")
    if model and model in around:
        return True
    # Part-number-shaped tokens around the photo, minus the
    # set's own model numbers (a card may cite its parent set).
    set_models = {
        norm_text(str(candidate.get("model") or ""))
        for candidate in page.get("candidates") or []
    }
    around_codes = set(_CODE_TOKEN_RE.findall(around)) - set_models
    if around_codes:
        return False
    name_tokens = [
        token
        for token in norm_text(piece.get("name") or "").split()
        if len(token) >= 3
    ]
    if not name_tokens:
        return False
    hits = sum(1 for token in name_tokens if token in around)
    return hits >= max(1, (len(name_tokens) + 1) // 2)


_CARD_PRICE_RE = re.compile(r"\$\s*(\d[\d,]*\.\d{2})")
_CARD_PART_NO_RE = re.compile(r"part\s*(?:no|number|#)\s*:?", re.IGNORECASE)


def _card_pieces(page: dict) -> list[dict]:
    """Pieces read straight off the page's product cards
    (row 200 fix, second round). The rendered loader's media
    inventory carries, for every photo, the text of the card
    around it; on a set page whose pieces are sold or shown
    as cards, each card states the piece's name, its part
    number and its price together, with its photo. The AI
    read treats those cards as separate products for sale
    and lists the contents line instead (names only) — so
    the cards are parsed directly: every value is a literal
    substring of the page's own card, grounded by
    construction. Generic by design: any shop that renders a
    set's pieces as priced, part-numbered cards qualifies; a
    page whose pieces are a plain text list yields no cards
    and the AI read covers it. The set's own card (its model
    is a page candidate) never becomes its own piece."""
    set_models = {
        norm_text(str(candidate.get("model") or ""))
        for candidate in page.get("candidates") or []
    }
    set_models.discard("")
    title_tokens = {
        token
        for token in norm_text(
            " ".join(
                str(part or "")
                for part in (
                    page.get("title", ""),
                    *(str(c.get("name") or "") for c in page.get("candidates") or []),
                )
            )
        ).split()
        if len(token) >= 4
    }
    cards: list[dict] = []
    seen: set[str] = set()
    for item in page.get("media") or []:
        context = " ".join(str(item.get("context") or "").split())
        if not context:
            continue
        price_match = _CARD_PRICE_RE.search(context)
        if not price_match:
            continue
        label_match = _CARD_PART_NO_RE.search(context)

        def _codes(text: str) -> list[str]:
            return [
                token
                for token in _CODE_TOKEN_RE.findall(norm_text(text))
                if token not in set_models and not token.isdigit()
            ]

        # The part number the card LABELS as such wins: card
        # text glues words together ("T30Part No: B30TXVA"),
        # and a whole-card scan can mistake the size for the
        # number. Only a card with no labelled number falls
        # back to its first part-number-shaped token.
        codes = _codes(context[label_match.end():]) if label_match else []
        if not codes:
            codes = _codes(context)
        if not codes:
            continue
        code = codes[0]
        if code in seen:
            continue
        # The piece's name is the card text ahead of its
        # "Part No:" label, or ahead of the part number
        # itself when the card prints no label.
        if label_match:
            name = context[: label_match.start()]
        else:
            code_match = re.search(re.escape(code), context, re.IGNORECASE)
            name = context[: code_match.start()] if code_match else ""
        name = name.strip(" \t-–—:|·•")
        if len(name) < 3 or not any(ch.isalpha() for ch in name):
            continue
        seen.add(code)
        cards.append(
            {
                "name": name[:120],
                "model": code.upper(),
                "msrp": float(price_match.group(1).replace(",", "")),
                "image_url": item.get("src"),
                "_shares_title": bool(
                    title_tokens
                    & {t for t in norm_text(name).split() if len(t) >= 4}
                ),
            }
        )
        if len(cards) >= 100:
            break
    if len(cards) < 3:
        return []
    # Prefer the cluster that belongs to THIS product (its
    # cards echo the product's name); unrelated priced cards
    # elsewhere on the page fall away when that cluster is
    # big enough to be the set's own grid.
    shared = [card for card in cards if card.pop("_shares_title")]
    for card in cards:
        card.pop("_shares_title", None)
    return shared if len(shared) >= 3 else cards


def _merge_card_pieces(pieces: list[dict], cards: list[dict]) -> list[dict]:
    """Fold card-read pieces into the kit: a card enriches
    the listed piece it names (same part number, or a name
    the card's name fully covers) with the part number,
    price and photo the contents list lacked; cards no
    listed piece claims stand as pieces in their own right —
    they are the page's own listing of what it sells as the
    set's pieces."""
    if not cards:
        return pieces
    by_model = {str(card["model"]).upper(): card for card in cards}
    used: set[str] = set()
    merged: list[dict] = []
    for piece in pieces:
        piece = dict(piece)
        card = None
        model = str(piece.get("model") or "").upper()
        if model and model in by_model:
            card = by_model[model]
        else:
            name_tokens = norm_text(piece.get("name") or "").split()
            # The piece's distinguishing tokens are the ones
            # carrying a digit (its size: T8, 10mm, 3/8) —
            # the two reads phrase the rest differently
            # ("T8 Torx Bit Socket" vs "1/4 DRIVE TORX T8"),
            # so match on those, uniquely; the full-name
            # cover remains as the fallback for names with
            # no digit in them.
            digit_tokens = [
                token
                for token in name_tokens
                if len(token) >= 2 and any(ch.isdigit() for ch in token)
            ]
            pools = [digit_tokens, name_tokens] if digit_tokens else [name_tokens]
            for wanted in pools:
                if len(wanted) < 1 or (wanted is name_tokens and len(wanted) < 2):
                    continue
                matches = [
                    candidate
                    for candidate in cards
                    if str(candidate["model"]).upper() not in used
                    and all(
                        token in norm_text(candidate["name"]).split()
                        for token in wanted
                    )
                ]
                if len(matches) == 1:
                    card = matches[0]
                    break
        if card is not None:
            used.add(str(card["model"]).upper())
            if not piece.get("model"):
                piece["model"] = card["model"]
            if piece.get("msrp") in (None, ""):
                piece["msrp"] = card["msrp"]
            if not piece.get("image_url"):
                piece["image_url"] = card["image_url"]
        merged.append(piece)
    for card in cards:
        if str(card["model"]).upper() not in used:
            merged.append(
                {
                    "name": card["name"],
                    "model": card["model"],
                    "msrp": card["msrp"],
                    "image_url": card["image_url"],
                }
            )
    return merged


def _validate_pieces(raw_pieces: object, page: dict) -> list[dict]:
    """AI-proposed set pieces, kept only as far as the page
    supports them: a piece survives on a supported name or part
    number; an unsupported part number is dropped (the piece
    stays), an unsupported price is dropped (never invented).
    Capped at 64, de-duplicated by name+model."""
    if not isinstance(raw_pieces, list):
        return []
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_pieces:
        if not isinstance(raw, dict):
            continue
        name = _as_text(raw.get("name"))
        model = _as_text(raw.get("model")) or _as_text(raw.get("part_number"))
        if name and not value_supported(name, page):
            name = ""
        if model and not value_supported(model, page):
            model = ""
        if not name and not model:
            continue
        piece: dict = {"name": name or model}
        if model:
            piece["model"] = model
        price = raw.get("msrp")
        if price is None:
            price = raw.get("price")
        if price is not None and money_supported(price, page):
            piece["msrp"] = float(price)
        image_url = _as_text(raw.get("image_url"))
        if image_url and _piece_photo_supported(piece, image_url, page):
            piece["image_url"] = image_url
        key = (norm_text(piece["name"]), norm_text(model or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(piece)
        if len(out) >= 64:
            break
    return out


# -- extraction -----------------------------------------------------------------

_AI_SYSTEM = (
    "You read tool product pages and extract the facts they "
    "state. Reply with a single JSON object only."
)


def _choose_candidate(page: dict, model: str) -> dict | None:
    """The page's structured record for this product: the one
    whose model matches the looked-up model, else the first."""
    candidates = page["candidates"]
    wanted = norm_text(model)
    if wanted:
        for candidate in candidates:
            if norm_text(str(candidate.get("model", ""))) == wanted:
                return candidate
    return candidates[0] if candidates else None


def _structured_fields(page: dict, brand: str, model: str) -> dict:
    """Deterministic pass: the page's own structured product
    record. When several records exist, the one whose model
    matches the looked-up model wins; otherwise the first with
    a name. Page-supported by construction — no validation
    needed beyond relevance."""
    chosen = _choose_candidate(page, model)
    fields = {
        key: chosen[key]
        for key in _FIELDS
        if chosen is not None and chosen.get(key) not in (None, "")
    }
    if "description" not in fields:
        meta = " ".join(str(page.get("meta_description") or "").split())
        if 20 <= len(meta) <= 2000:
            fields["description"] = meta
    return fields


# The most page text the AI pass reads. A rendered page's
# visible text usually runs 5–20k characters; the whole text
# fits the read for most pages, and the windowed fallback
# below only has to serve genuinely huge ones.
_EXCERPT_LIMIT = 16_000

# Generic retail vocabulary for a set's contents list — the
# region of the page the windowed excerpt must never lose.
_CONTENTS_MARKERS = (
    "set details",
    "what's included",
    "whats included",
    "set includes",
    "kit includes",
    "box contents",
    "in the box",
    "includes",
    "contents",
)


def page_excerpt(page: dict, model: str) -> str:
    """The page text the AI reads. Whole text when it fits —
    a set's contents list can sit anywhere on the page, and
    the first live Matco read (row 200) showed a head-only
    excerpt cutting that list in half, so the AI fell back
    to the size list in the description and returned pieces
    with no part numbers or prices. For longer pages: the
    head, a window around the model string when it shows up
    deep, and windows around the contents markers."""
    text = page["text"]
    if len(text) <= _EXCERPT_LIMIT:
        return text
    windows: list[tuple[int, int]] = [(0, 5000)]
    if model:
        index = text.lower().find(model.lower())
        if index > 4000:
            windows.append((index - 500, index + 4500))
    lowered = text.lower()
    for marker in _CONTENTS_MARKERS:
        index = lowered.find(marker)
        if index >= 0:
            windows.append((index - 250, index + 4750))
    windows.sort()
    merged: list[list[int]] = []
    for start, end in windows:
        start = max(0, start)
        end = min(len(text), end)
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    parts: list[str] = []
    total = 0
    for start, end in merged:
        if total >= _EXCERPT_LIMIT:
            break
        piece = text[start:end]
        parts.append(piece)
        total += len(piece)
    return "\n...\n".join(parts)[:_EXCERPT_LIMIT]


def _ai_extract_fields(
    db: Session, page: dict, brand: str, model: str
) -> tuple[dict, dict, dict]:
    """AI pass over the fetched page ONLY, for fields the
    structured pass didn't settle — plus the set contents (row
    195): the pieces the page lists and the piece count it
    states — plus, since row 199, the page's specification
    pairs and its stated warranty: the lookup pulls everything
    the page states that the system has a field for. Every
    proposed value must be supported by the page evidence or
    it is dropped — the model is a reader here, never a
    source. Raises ai_service errors (dark seam / provider
    failure): the caller treats either as "no AI pass", never
    as a failed page. Returns (fields, kit, extras)."""
    digest = json.dumps(page["candidates"])[:3500] if page["candidates"] else ""
    # Row 200: the page's photo inventory (the rendered
    # loader's media list) — the only photos a piece may be
    # paired with, each with the text of the card around it.
    media_lines = ""
    if page.get("media"):
        # Priced-card photos first: a photo whose card text
        # carries a price or a part number is the kind a set
        # piece pairs with; gallery and banner shots follow.
        # The list the AI sees stays short, so the pairing
        # candidates must be the right ones (row 200 fix).
        def _card_rank(item: dict) -> int:
            label = f"{item.get('context') or ''} {item.get('alt') or ''}"
            return 0 if ("$" in label or _CODE_TOKEN_RE.search(label.lower())) else 1

        lines = []
        for item in sorted(page["media"], key=_card_rank)[:20]:
            label = item.get("context") or item.get("alt") or ""
            lines.append(f"- {item['src']} — {label}" if label else f"- {item['src']}")
        media_lines = "\nPhotos on the page:\n" + "\n".join(lines)
    hint = " ".join(part for part in (brand, model) if part).strip()
    prompt = (
        "Below is the text of ONE product page"
        + (f' (for "{hint}")' if hint else "")
        + ". Extract the product facts THE PAGE states. Use ONLY "
        "facts written on this page — never outside knowledge, "
        "never a guess. Reply with a JSON object with keys among "
        '{"name","brand","model","category","size","msrp","description",'
        '"upc","pieces","piece_count","specs","warranty"} '
        "(msrp a number in USD, size a short string like "
        '"1/2 in drive", description the page\'s own product '
        "description copied as written, not rewritten, upc the "
        "product's barcode / GTIN digits when the page states "
        "them). Omit any key the page does not state. If the "
        "product is a set or kit, also give \"pieces\": the "
        "individual pieces the page lists as included (a "
        "contents / set includes list), each an object "
        '{"name","model","msrp","image_url"} with the piece\'s '
        "own name, its part number as \"model\" when the page "
        "gives one, its own price as \"msrp\" when the page "
        "prices it separately, and \"image_url\" ONLY when the "
        "Photos list below shows a photo whose caption names "
        "that piece — and \"piece_count\": the number of pieces "
        "the page states the set contains. Omit both when the "
        "page does not list the contents. Also give \"specs\": "
        "an object of the specification name/value pairs the "
        "page's specifications table or details list states "
        "(drive size, weight, finish, material, dimensions — "
        "as written), and \"warranty\": the warranty the page "
        "states, copied as written (e.g. \"Lifetime warranty\" "
        "or \"2 year limited warranty\"). Omit both when the "
        "page does not state them.\n\n"
        f"Page title: {page['title']}\n"
        + (f"Structured product data on the page: {digest}\n" if digest else "")
        + f"\nPage text:\n{page_excerpt(page, model)}"
        + media_lines
    )
    data = ai_service.complete_json(
        db, prompt, system=_AI_SYSTEM, temperature=0.0
    )
    out: dict = {}
    for key in _FIELDS:
        value = data.get(key)
        if value in (None, ""):
            continue
        if key == "msrp":
            if money_supported(value, page):
                out[key] = value
        elif key == "description":
            # A description counts only when it is a real
            # sentence the page supports — token-checked like
            # every other value, plus the length bounds that
            # keep nav chrome and page dumps out.
            if (
                isinstance(value, str)
                and 20 <= len(value.strip()) <= 1000
                and value_supported(value, page)
            ):
                out[key] = " ".join(value.split())
        elif value_supported(value, page):
            out[key] = str(value).strip()
    if out.get("brand"):
        out["brand"] = canonical_brand(out["brand"])
    if out.get("upc"):
        # A barcode is digits only, of a plausible length —
        # anything else the reader proposed is not a barcode.
        digits = re.sub(r"\D", "", str(out["upc"]))
        if 8 <= len(digits) <= 14:
            out["upc"] = digits
        else:
            out.pop("upc", None)
    # A "name" that merely restates the model (or brand+model)
    # the user typed is not a name the page gave us.
    name = out.get("name")
    if name:
        echoes = {
            norm_text(model),
            norm_text(f"{brand} {model}"),
            norm_text(brand),
        }
        if norm_text(name) in echoes:
            out.pop("name", None)
    # Row 195: the set contents the page lists + the count it
    # states, each validated against the page evidence.
    kit: dict = {"pieces": _validate_pieces(data.get("pieces"), page)}
    raw_count = data.get("piece_count")
    if (
        isinstance(raw_count, int)
        and not isinstance(raw_count, bool)
        and 2 <= raw_count <= 500
        and piece_count_supported(raw_count, page)
    ):
        kit["piece_count"] = raw_count
    # Row 199: the page's spec pairs + stated warranty, each
    # validated against the page evidence like everything else.
    extras: dict = {}
    raw_specs = data.get("specs")
    if isinstance(raw_specs, dict):
        specs: dict = {}
        for spec_name, spec_value in raw_specs.items():
            name = _as_text(spec_name)
            value = spec_value
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = str(value)
            value = _as_text(value)
            if (
                name
                and value
                and len(name) <= 80
                and len(value) <= 200
                and value_supported(name, page)
                and value_supported(value, page)
            ):
                specs[name] = value
            if len(specs) >= 20:
                break
        if specs:
            extras["specs"] = specs
    raw_warranty = data.get("warranty")
    if isinstance(raw_warranty, str) and value_supported(raw_warranty, page):
        extras.update(_warranty_from_text(" ".join(raw_warranty.split())))
    return out, kit, extras


def extract_fields(
    db: Session, page: dict, brand: str, model: str
) -> tuple[dict, bool, dict, dict]:
    """All grounded facts one page yields: (fields, ai_used,
    kit, extras). Structured first, AI-read gaps second. The
    AI pass runs while any of name/category/size is still
    missing and the seam is lit (the wizard wants as many
    fields filled as the page supports) — and, since row 195,
    also when the page presents a set whose contents aren't
    structured yet, so the pieces get read too — and, since
    row 199, also while the page's spec pairs haven't been
    read yet: the lookup pulls everything the page states.
    A dark or failing AI never costs the page's own structured
    facts. On a search/listing page the AI pass is skipped
    entirely: its text mixes many products, and only the
    page's discrete structured records (chosen by exact model
    match) are safe to read there."""
    fields = _structured_fields(page, brand, model)
    chosen = _choose_candidate(page, model)
    kit: dict = {
        "pieces": list(chosen.get("pieces") or []) if chosen else [],
        "piece_count": detect_piece_count(
            str(fields.get("name") or ""),
            str(fields.get("description") or ""),
            page.get("title", ""),
        ),
    }
    # Row 199 extras: the spec pairs the structured record
    # carries, and the warranty the product's own description
    # states (a deterministic read of page-supported text).
    extras: dict = {}
    if chosen and chosen.get("specs"):
        extras["specs"] = dict(chosen["specs"])
    if fields.get("description"):
        extras.update(_warranty_from_text(str(fields["description"])))
    looks_like_set = kit["piece_count"] is not None or bool(
        _SET_WORD_RE.search(
            " ".join(
                str(part or "")
                for part in (fields.get("name"), page.get("title"))
            )
        )
    )
    ai_used = False
    if (
        ai_service.ai_configured(db)
        and not _is_listing_url(page.get("url", ""))
        and (
            any(
                key not in fields
                for key in ("name", "category", "size", "description")
            )
            or (looks_like_set and not kit["pieces"])
            or not extras.get("specs")
        )
    ):
        ai_used = True
        try:
            ai_fields, ai_kit, ai_extras = _ai_extract_fields(db, page, brand, model)
        except (ai_service.AiNotConfigured, ai_service.AiProviderError):
            ai_fields, ai_kit, ai_extras = {}, {"pieces": []}, {}
        for key, value in ai_fields.items():
            fields.setdefault(key, value)
        if not kit["pieces"] and ai_kit.get("pieces"):
            kit["pieces"] = ai_kit["pieces"]
        if kit["piece_count"] is None and ai_kit.get("piece_count"):
            kit["piece_count"] = ai_kit["piece_count"]
        if ai_extras.get("specs"):
            merged_specs = dict(ai_extras["specs"])
            merged_specs.update(extras.get("specs") or {})
            extras["specs"] = merged_specs
        for key in ("warranty_type", "warranty_months", "warranty_terms"):
            if key not in extras and ai_extras.get(key) is not None:
                extras[key] = ai_extras[key]
    if looks_like_set:
        # Row 200 fix, second round: pieces the page renders
        # as priced, part-numbered product cards are read
        # straight off the cards and folded into the kit —
        # the AI read lists the contents line (names only)
        # and treats the cards as separate products, so
        # without this the part numbers, prices and piece
        # photos the page plainly states never arrive.
        cards = _card_pieces(page)
        if cards:
            kit["pieces"] = _merge_card_pieces(kit["pieces"], cards)
            if kit["piece_count"] is None and len(kit["pieces"]) >= 2:
                kit["piece_count"] = len(kit["pieces"])
    if "warranty_type" not in extras:
        # The stated warranty often lives in the features text
        # rather than the description field — one deterministic
        # scan of the product-focused excerpt, page-supported
        # by construction.
        extras.update(_warranty_from_text(page_excerpt(page, model)))
    return fields, ai_used, kit, extras


# -- search (the AI provider's web search, through the AI seam) -----------------
#
# One vendor for brain and eyes (owner's decision, 2026-10-25):
# ai_service.web_search does the searching; this pipe consumes
# ONLY its citation URLs. Routing discipline on top:
# * manufacturer-looking hosts before other product pages,
# search/listing pages LAST (a listing page's text mixes
# many products — it is walked to, never read as a source,
# until nothing better exists);
# * citation payloads are transient routing only — titles and
# answer text are never carried, stored, returned, or used
# as evidence. The only things this pipe keeps are facts
# extracted from the FETCHED PAGE plus that page's URL
# (see _result), so search_pages still drops everything
# except the URL at the boundary.


def search_configured(db: Session) -> bool:
    return manuals.web_search_configured(db)


_LISTING_PATH_HINTS = ("/search", "catalogsearch", "/category", "/listing")
_LISTING_QUERY_KEYS = {"q", "query", "keyword", "keywords"}


def _is_listing_url(url: str) -> bool:
    """True when a URL has the shape of a search-results or
    listing page rather than one product's page."""
    parsed = urlparse(url or "")
    path = parsed.path.lower()
    if any(hint in path for hint in _LISTING_PATH_HINTS):
        return True
    if "product" in path or "/p/" in path:
        return False
    keys = {key.lower() for key, _ in parse_qsl(parsed.query)}
    return bool(keys & _LISTING_QUERY_KEYS)


def _host_matches_hint(host: str, hint: str) -> bool:
    """True when the host carries one of the hint's words (the
    brand, typically): matcotools.com for "Matco SPRB4A" — the
    closest a URL alone gets to "manufacturer's own page"."""
    squashed_host = re.sub(r"[^a-z0-9]", "", (host or "").lower())
    if not squashed_host:
        return False
    for token in re.split(r"[^A-Za-z0-9]+", hint or ""):
        word = re.sub(r"[^a-z0-9]", "", token.lower())
        if len(word) >= 4 and word in squashed_host:
            return True
    return False


def _url_carries_exact_model(url: str, model: str) -> bool:
    """True when one of the URL's path segments IS the model,
    exactly — /product/dcf891/ names the bare tool, while
    /product/dcf891p2/ names the kit variant (C-08: the variant
    page winning the walk is how a typed DCF891 came back as
    model DCF891P2)."""
    wanted = re.sub(r"[^a-z0-9]", "", (model or "").lower())
    if not wanted:
        return False
    path = urlparse(url or "").path.lower()
    segments = re.split(r"[^a-z0-9]+", path)
    return wanted in segments


def rank_candidate_urls(urls: list[str], hint: str, model: str = "") -> list[str]:
    """Citation URLs in the order the walk should try them:
    manufacturer-looking product pages, then other product
    pages, then search/listing pages — citation order breaks
    every tie. Within the product pages, a URL whose path
    carries the typed model EXACTLY walks before one that
    merely contains it (a variant's address) — C-08."""

    def key(item: tuple[int, str]) -> tuple[bool, bool, bool, int]:
        index, url = item
        host = urlparse(url).hostname or ""
        return (
            _is_listing_url(url),
            not _url_carries_exact_model(url, model),
            not _host_matches_hint(host, hint),
            index,
        )

    return [url for _, url in sorted(enumerate(urls), key=key)]


def search_pages(
    db: Session, query: str, count: int = 5, model: str = ""
) -> list[dict]:
    """Citation URLs for a query, ranked for the walk and
    reduced to [{url}] (see the posture note above). Empty
    while the AI seam is dark, and empty when a search fails
    or cites nothing usable."""
    if not search_configured(db):
        return []
    try:
        results = ai_service.web_search(db, query, max_results=max(count, 8))
    except (ai_service.AiNotConfigured, ai_service.AiProviderError):
        return []
    urls = [result["url"] for result in results]
    return [{"url": url} for url in rank_candidate_urls(urls, query, model)[:count]]


# -- the grounded lookup --------------------------------------------------------

# The search walk's budgets: ranked citations plus at most two
# followed links off walked pages, eight fetches in total (row
# 199 raised it from six: the walk now keeps reading pages to
# fill the first page's gaps instead of stopping at it).
_MAX_SEARCH_FETCHES = 8
_MAX_FOLLOWED_LINKS = 2

# Row 214: the full walk also runs against the clock. A set
# whose maker never prices the pieces individually can never
# satisfy _result_complete, so the fetch budget alone lets
# the walk run past the two-minute edge timeout and the
# import dies unanswered (live: Mac Tools SX126TR, twice,
# 2026-11-20). Seventy seconds leaves the route room to
# answer with the best result the walk already holds.
_WALK_BUDGET_SECONDS = 70.0


def _fallback_queries(brand: str, model: str, primary: str) -> list[str]:
    """Row 214: the deeper hunt's search phrasings, tried in
    order when the first search surfaces nothing the walk can
    use. The first search's wording is the plain brand +
    model; a search layer that misses the maker's own page
    for an exact part number gets asked differently before
    the lookup is allowed to answer a miss: the model in
    quotes, a search aimed at the brand's own likely site,
    and the quoted model on its own."""
    out: list[str] = []
    if model:
        out.append(f'"{model}" {brand}'.strip())
        host = re.sub(r"[^a-z0-9-]", "", (brand or "").lower().replace(" ", ""))
        if host:
            out.append(f"site:{host}.com {model}")
        out.append(f'"{model}"')
    seen: set[str] = set()
    queries: list[str] = []
    for candidate in out:
        key = candidate.lower()
        if candidate and key != primary.lower() and key not in seen:
            seen.add(key)
            queries.append(candidate)
    return queries


def _result(
    page: dict,
    fields: dict,
    ai_used: bool,
    kit: dict | None = None,
    extras: dict | None = None,
) -> dict:
    kit = kit or {"pieces": []}
    extras = extras or {}
    return {
        "fields": fields,
        "image_url": page["image_url"] or None,
        "source_name": page["site_name"],
        "source_url": page["url"],
        "ai_used": ai_used,
        # Row 195: the set contents read off this page (each
        # piece page-supported; empty for non-sets).
        "pieces": kit.get("pieces") or [],
        "piece_count": kit.get("piece_count"),
        # Row 199: everything else the page states that the
        # system has a home for — the whole photo gallery, the
        # spec pairs, the stated warranty.
        "photos": list(page.get("images") or []),
        "specs": dict(extras.get("specs") or {}),
        "warranty_type": extras.get("warranty_type"),
        "warranty_months": extras.get("warranty_months"),
        "warranty_terms": extras.get("warranty_terms"),
    }


def _piece_richness(pieces: list) -> int:
    """How much per-piece detail a contents list carries
    (part numbers + prices + photos across its pieces) — the
    merge walk keeps the richest list it finds."""
    return sum(
        1
        for piece in pieces
        for key in ("model", "msrp", "image_url")
        if isinstance(piece, dict) and piece.get(key) not in (None, "")
    )


def _merge_into(primary: dict, other: dict, model: str) -> None:
    """Fill the primary result's gaps from another walked
    page's result (row 199). Identity facts (name, brand,
    model) never move; msrp fills only from a page whose model
    matches the typed model exactly; every value merged was
    validated against its own page by extraction."""
    fields = primary["fields"]
    for key, value in other["fields"].items():
        if key in fields or value in (None, ""):
            continue
        if key in ("name", "brand", "model"):
            continue
        if key == "msrp" and model:
            if norm_text(str(other["fields"].get("model", ""))) != norm_text(model):
                continue
        fields[key] = value
    other_pieces = other.get("pieces") or []
    if other_pieces:
        primary_pieces = primary.get("pieces") or []
        if not primary_pieces:
            primary["pieces"] = other_pieces
        elif _piece_richness(other_pieces) > _piece_richness(primary_pieces):
            # Enrich, never just swap: the richer list's part
            # numbers, prices and photos fold into the pieces
            # the primary already listed, and pieces it never
            # listed join it. A page whose grid mounts one
            # card fewer than another page listed must not
            # cost the set its missing piece — the old
            # swap-only rule left a names-only contents list
            # standing whenever the priced page showed one
            # piece less.
            cards = [
                {
                    "name": str(piece.get("name") or piece.get("model") or ""),
                    "model": piece["model"],
                    "msrp": piece.get("msrp"),
                    "image_url": piece.get("image_url"),
                }
                for piece in other_pieces
                if isinstance(piece, dict) and piece.get("model")
            ]
            if cards:
                primary["pieces"] = _merge_card_pieces(primary_pieces, cards)
            else:
                primary["pieces"] = other_pieces
    if primary.get("piece_count") is None and other.get("piece_count"):
        primary["piece_count"] = other["piece_count"]
    for key, value in (other.get("specs") or {}).items():
        primary["specs"].setdefault(key, value)
    for photo in other.get("photos") or []:
        if photo not in primary["photos"] and len(primary["photos"]) < 8:
            primary["photos"].append(photo)
    for key in ("warranty_type", "warranty_months", "warranty_terms"):
        if primary.get(key) in (None, "") and other.get(key) not in (None, ""):
            primary[key] = other[key]
    primary["ai_used"] = primary["ai_used"] or other["ai_used"]


def _pieces_priced(pieces: list) -> bool:
    """True when a set's contents carry the facts the system
    collects for a piece: at least half the pieces hold both
    a part number and a price. A contents list of bare names
    (a resale listing that names the pieces but prices none
    of them) is not the finished contents — the priced pieces
    live on the maker's own page, and the walk keeps hunting
    until it finds them or runs out of pages."""
    if not pieces:
        return False
    priced = sum(
        1
        for piece in pieces
        if isinstance(piece, dict)
        and piece.get("model")
        and piece.get("msrp") is not None
    )
    return priced * 2 >= len(pieces)


def _result_complete(result: dict) -> bool:
    """True when a result holds everything the walk could
    still gain: every field, the contents of a set (priced,
    not just named), specs."""
    fields = result["fields"]
    if any(key not in fields for key in _FIELDS):
        return False
    if not result.get("specs"):
        return False
    name = str(fields.get("name") or "")
    if _SET_WORD_RE.search(name) and not _pieces_priced(
        result.get("pieces") or []
    ):
        return False
    return True


def grounded_product(
    db: Session,
    *,
    brand: str = "",
    model: str = "",
    link: str = "",
    quick: bool = False,
) -> dict | None:
    """One grounded answer, or None when no page yields one.

    Link mode: read THAT page (PageFetchError propagates — the
    caller reports the page couldn't be read). Search mode:
    the ranked citations are walked (manufacturer-looking
    product pages first, search/listing pages last); the first
    exact-model page that names the product anchors the answer
    and further exact-model pages fill its gaps (row 199), and
    a page is only read at all when it mentions the model
    sought (a roundup page about other products is not a
    source for this one). When
    a walked page yields no name, the walk may follow up to
    _MAX_FOLLOWED_LINKS of that page's own same-host links
    that carry the model in their address — the one hop from
    a listing page to the product page it lists. Fetches are
    capped at _MAX_SEARCH_FETCHES in total. When several pages
    name a product, the page whose model matches the typed
    model EXACTLY wins; a variant page (kit / tool-only suffix)
    answers only when no exact page does, and the chain flags
    that substitution in its result (C-08).

    quick=True (row 203) is the wizard's first pass: downloads
    only, the first pages only — the basic facts fast, with
    the full walk left to the full-information import."""
    if link:
        page = fetch_product_page(link, allow_render=not quick)
        fields, ai_used, kit, extras = extract_fields(db, page, brand, model)
        return _result(page, fields, ai_used, kit, extras)
    if not search_configured(db):
        return None
    query = " ".join(part for part in (brand, model) if part).strip()
    if not query:
        return None
    queue = [
        result["url"] for result in search_pages(db, query, count=8, model=model)
    ]
    seen: set[str] = set()
    fetches = 0
    followed = 0
    model_squashed = re.sub(r"[^a-z0-9]", "", (model or "").lower())
    best_partial: dict | None = None
    best_variant: dict | None = None
    # Row 199: the first exact-model page that names the product
    # anchors the answer, and the walk keeps reading further
    # exact-model pages to fill the anchor's gaps (contents,
    # specs, barcode, photos) instead of stopping at the first
    # page — the lookup pulls everything the sources state.
    anchor: dict | None = None
    merge_sources: list[dict] = []
    absorbed = 0

    def absorb() -> None:
        nonlocal absorbed
        if anchor is None:
            return
        while absorbed < len(merge_sources):
            _merge_into(anchor, merge_sources[absorbed], model)
            absorbed += 1

    # Row 203: the quick pass reads at most the first couple
    # of pages, downloads only — no browser reads, no link
    # hops, no merge walk. It answers with the basic facts;
    # the full pass (the default) does the whole walk.
    max_fetches = 2 if quick else _MAX_SEARCH_FETCHES
    # Row 214: the full walk answers inside its time budget
    # with the best result it already holds rather than
    # running past the edge timeout (see _WALK_BUDGET_SECONDS).
    started = time.monotonic()

    def within_budget() -> bool:
        return quick or (time.monotonic() - started) < _WALK_BUDGET_SECONDS

    def walk(walk_queue: list[str]) -> None:
        nonlocal fetches, followed, anchor, best_variant, best_partial
        while walk_queue and fetches < max_fetches and within_budget():
            url = walk_queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                page = fetch_product_page(url, allow_render=not quick)
            except PageFetchError:
                continue
            fetches += 1
            if model and norm_text(model) not in page["evidence"]:
                continue
            fields, ai_used, kit, extras = extract_fields(db, page, brand, model)
            result = _result(page, fields, ai_used, kit, extras)
            found_model = norm_text(str(fields.get("model", "")))
            exact = not model or not found_model or found_model == norm_text(model)
            if fields.get("name"):
                if exact:
                    if anchor is None:
                        anchor = result
                    else:
                        merge_sources.append(result)
                else:
                    # A named page for a DIFFERENT version of the
                    # tool (typed DCF891, page is the DCF891P2 kit
                    # — C-08): hold it as the fallback and keep
                    # walking — an exact-model page later in the
                    # queue beats it. The chain flags the
                    # substitution when this fallback is what
                    # finally answers; it is never silent. A variant
                    # never fills the exact page's gaps: its
                    # contents describe the variant, not this tool.
                    if best_variant is None or len(fields) > len(
                        best_variant["fields"]
                    ):
                        best_variant = result
            elif fields:
                if best_partial is None or len(fields) > len(best_partial["fields"]):
                    best_partial = result
                if exact:
                    # A page that carries this model's facts
                    # (contents, specs) without naming it in a
                    # field can still fill the anchor's gaps.
                    merge_sources.append(result)
            absorb()
            if anchor is not None and _result_complete(anchor):
                return
            if quick:
                # No link hops on the quick pass — the first
                # pages either name the product or they don't.
                continue
            if model_squashed and followed < _MAX_FOLLOWED_LINKS:
                for link_url in page["links"]:
                    if followed >= _MAX_FOLLOWED_LINKS:
                        break
                    if link_url in seen or link_url in walk_queue:
                        continue
                    if urlparse(link_url).hostname != page["host"]:
                        continue
                    squashed = re.sub(r"[^a-z0-9]", "", link_url.lower())
                    if model_squashed in squashed:
                        walk_queue.append(link_url)
                        followed += 1

    walk(queue)
    if (
        not quick
        and anchor is None
        and best_variant is None
        and best_partial is None
    ):
        # Row 214: a clean miss so far is not the end of the
        # hunt. The first search sometimes never surfaces the
        # maker's own page for an exact part number (live:
        # SABCTX13VA, 2026-11-20) — ask the search differently
        # and walk what comes back before answering a miss.
        for fallback_query in _fallback_queries(brand, model, query):
            if fetches >= max_fetches or not within_budget():
                break
            fresh = [
                result["url"]
                for result in search_pages(db, fallback_query, count=8, model=model)
                if result["url"] not in seen
            ]
            if fresh:
                walk(fresh)
            if anchor is not None:
                break
    if anchor is not None:
        absorb()
        return anchor
    return best_variant or best_partial


# -- photo download (the wizard's "Use this photo") -----------------------------


def fetch_photo(url: str) -> tuple[bytes, str, str]:
    """Download the product photo a grounded page offered, with
    the same guards as a manual import: https + public hosts
    only (manuals.assert_safe_url via validate), the photo
    content-type allowlist, a byte sniff, and the 10 MB photo
    cap. Returns (bytes, content_type, filename). Raises
    PageFetchError with plain copy."""
    cleaned = validate_page_url(url)
    try:
        data, content_type = manuals._download(cleaned)
    except manuals.ManualError as exc:
        raise PageFetchError(str(exc)) from exc
    if len(data) > _PHOTO_MAX_BYTES:
        raise PageFetchError("That photo is larger than the 10 MB photo limit.")
    if content_type not in ALLOWED_CONTENT_TYPES["photo"]:
        if data[:3] == b"\xff\xd8\xff":
            content_type = "image/jpeg"
        elif data[:8] == b"\x89PNG\r\n\x1a\n":
            content_type = "image/png"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            content_type = "image/webp"
        else:
            raise PageFetchError("That link didn't lead to a photo file.")
    elif not content_matches_declared(content_type, data[:512]):
        raise PageFetchError("That link didn't lead to a photo file.")
    path_name = urlparse(cleaned).path.rsplit("/", 1)[-1]
    if not path_name or "." not in path_name:
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[
            content_type
        ]
        path_name = f"product-photo{ext}"
    return data, content_type, storage.safe_filename(path_name)
