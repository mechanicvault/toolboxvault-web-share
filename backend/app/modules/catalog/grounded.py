"""Grounded web lookup (owner fix, 2026-10-25) — the pipe that
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

_FIELDS = ("name", "brand", "model", "category", "size", "msrp", "description")

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
    # The product description (AI wizard completion, 2026-11-07):
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
    return out


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


def parse_page(html: str, url: str) -> dict:
    """Parse fetched HTML into the extraction bundle: title,
    visible text, structured product records, the page's main
    image, and the normalized evidence every claimed fact is
    checked against."""
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


def fetch_product_page(url: str) -> dict:
    """Validate + fetch + parse one product page. Raises
    PageFetchError when the page can't be read."""
    cleaned = validate_page_url(url)
    return parse_page(_fetch_html(cleaned), cleaned)


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


# -- extraction -----------------------------------------------------------------

_AI_SYSTEM = (
    "You read tool product pages and extract the facts they "
    "state. Reply with a single JSON object only."
)


def _structured_fields(page: dict, brand: str, model: str) -> dict:
    """Deterministic pass: the page's own structured product
    record. When several records exist, the one whose model
    matches the looked-up model wins; otherwise the first with
    a name. Page-supported by construction — no validation
    needed beyond relevance."""
    candidates = page["candidates"]
    chosen = None
    wanted = norm_text(model)
    if wanted:
        for candidate in candidates:
            if norm_text(str(candidate.get("model", ""))) == wanted:
                chosen = candidate
                break
    if chosen is None and candidates:
        chosen = candidates[0]
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


def page_excerpt(page: dict, model: str) -> str:
    """The page text the AI reads: the head (title/specs live
    early) plus a window around the model string when it shows
    up deeper in the page."""
    text = page["text"]
    excerpt = text[:5000]
    if model:
        index = text.lower().find(model.lower())
        if index > 4000:
            excerpt += "\n...\n" + text[index - 500 : index + 4500]
    return excerpt[:10000]


def _ai_extract_fields(db: Session, page: dict, brand: str, model: str) -> dict:
    """AI pass over the fetched page ONLY, for fields the
    structured pass didn't settle. Every proposed value must be
    supported by the page evidence or it is dropped — the model
    is a reader here, never a source. Raises ai_service errors
    (dark seam / provider failure): the caller treats either as
    "no AI pass", never as a failed page."""
    digest = json.dumps(page["candidates"])[:3500] if page["candidates"] else ""
    hint = " ".join(part for part in (brand, model) if part).strip()
    prompt = (
        "Below is the text of ONE product page"
        + (f' (for "{hint}")' if hint else "")
        + ". Extract the product facts THE PAGE states. Use ONLY "
        "facts written on this page — never outside knowledge, "
        "never a guess. Reply with a JSON object with keys among "
        '{"name","brand","model","category","size","msrp","description"} '
        "(msrp a number in USD, size a short string like "
        '"1/2 in drive", description the page\'s own product '
        "description copied as written, not rewritten). Omit any "
        "key the page does not state.\n\n"
        f"Page title: {page['title']}\n"
        + (f"Structured product data on the page: {digest}\n" if digest else "")
        + f"\nPage text:\n{page_excerpt(page, model)}"
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
    return out


def extract_fields(db: Session, page: dict, brand: str, model: str) -> tuple[dict, bool]:
    """All grounded fields one page yields, plus whether an AI
    call ran: structured first, AI-read gaps second. The AI
    pass runs while any of name/category/size is still missing
    and the seam is lit (the wizard wants as many fields filled
    as the page supports) — a dark or failing AI never costs
    the page's own structured facts. On a search/listing page
    the AI pass is skipped entirely: its text mixes many
    products, and only the page's discrete structured records
    (chosen by exact model match) are safe to read there."""
    fields = _structured_fields(page, brand, model)
    ai_used = False
    if (
        ai_service.ai_configured(db)
        and not _is_listing_url(page.get("url", ""))
        and any(
            key not in fields for key in ("name", "category", "size", "description")
        )
    ):
        ai_used = True
        try:
            ai_fields = _ai_extract_fields(db, page, brand, model)
        except (ai_service.AiNotConfigured, ai_service.AiProviderError):
            ai_fields = {}
        for key, value in ai_fields.items():
            fields.setdefault(key, value)
    return fields, ai_used


# -- search (the AI provider's web search, through the AI seam) -----------------
#
# One vendor for brain and eyes (owner's decision, 2026-10-25):
# ai_service.web_search does the searching; this pipe consumes
# ONLY its citation URLs. Routing discipline on top:
#   * manufacturer-looking hosts before other product pages,
#     search/listing pages LAST (a listing page's text mixes
#     many products — it is walked to, never read as a source,
#     until nothing better exists);
#   * citation payloads are transient routing only — titles and
#     answer text are never carried, stored, returned, or used
#     as evidence. The only things this pipe keeps are facts
#     extracted from the FETCHED PAGE plus that page's URL
#     (see _result), so search_pages still drops everything
#     except the URL at the boundary.


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
# followed links off walked pages, six fetches in total.
_MAX_SEARCH_FETCHES = 6
_MAX_FOLLOWED_LINKS = 2


def _result(page: dict, fields: dict, ai_used: bool) -> dict:
    return {
        "fields": fields,
        "image_url": page["image_url"] or None,
        "source_name": page["site_name"],
        "source_url": page["url"],
        "ai_used": ai_used,
    }


def grounded_product(
    db: Session,
    *,
    brand: str = "",
    model: str = "",
    link: str = "",
) -> dict | None:
    """One grounded answer, or None when no page yields one.

    Link mode: read THAT page (PageFetchError propagates — the
    caller reports the page couldn't be read). Search mode:
    the ranked citations are walked (manufacturer-looking
    product pages first, search/listing pages last); the first
    page that names the product wins, and a page is only read
    at all when it mentions the model sought (a roundup page
    about other products is not a source for this one). When
    a walked page yields no name, the walk may follow up to
    _MAX_FOLLOWED_LINKS of that page's own same-host links
    that carry the model in their address — the one hop from
    a listing page to the product page it lists. Fetches are
    capped at _MAX_SEARCH_FETCHES in total. When several pages
    name a product, the page whose model matches the typed
    model EXACTLY wins; a variant page (kit / tool-only suffix)
    answers only when no exact page does, and the chain flags
    that substitution in its result (C-08)."""
    if link:
        page = fetch_product_page(link)
        fields, ai_used = extract_fields(db, page, brand, model)
        return _result(page, fields, ai_used)
    if not search_configured(db):
        return None
    query = " ".join(part for part in (brand, model) if part).strip()
    if not query:
        return None
    queue = [
        result["url"] for result in search_pages(db, query, count=6, model=model)
    ]
    seen: set[str] = set()
    fetches = 0
    followed = 0
    model_squashed = re.sub(r"[^a-z0-9]", "", (model or "").lower())
    best_partial: dict | None = None
    best_variant: dict | None = None
    while queue and fetches < _MAX_SEARCH_FETCHES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            page = fetch_product_page(url)
        except PageFetchError:
            continue
        fetches += 1
        if model and norm_text(model) not in page["evidence"]:
            continue
        fields, ai_used = extract_fields(db, page, brand, model)
        if fields.get("name"):
            found_model = norm_text(str(fields.get("model", "")))
            if not model or not found_model or found_model == norm_text(model):
                return _result(page, fields, ai_used)
            # A named page for a DIFFERENT version of the tool
            # (typed DCF891, page is the DCF891P2 kit — C-08):
            # hold it as the fallback and keep walking — an
            # exact-model page later in the queue beats it. The
            # chain flags the substitution when this fallback is
            # what finally answers; it is never silent.
            if best_variant is None or len(fields) > len(best_variant["fields"]):
                best_variant = _result(page, fields, ai_used)
        elif fields and (
            best_partial is None or len(fields) > len(best_partial["fields"])
        ):
            best_partial = _result(page, fields, ai_used)
        if model_squashed and followed < _MAX_FOLLOWED_LINKS:
            for link_url in page["links"]:
                if followed >= _MAX_FOLLOWED_LINKS:
                    break
                if link_url in seen or link_url in queue:
                    continue
                if urlparse(link_url).hostname != page["host"]:
                    continue
                squashed = re.sub(r"[^a-z0-9]", "", link_url.lower())
                if model_squashed in squashed:
                    queue.append(link_url)
                    followed += 1
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
