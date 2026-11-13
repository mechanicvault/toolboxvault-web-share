"""Locate User Manual (wave 4; owner spec 2026-10-20;
re-tiered by the owner 2026-11-05).

The flow, exactly as specced:
  1. SEARCH by the item's brand + model for the manual
     DOCUMENT itself. The owner sharpened this on 2026-11-05:
     the old search led with website LINKS (the manufacturer's
     support home, web pages) and only ever pulled a file when
     the AI seam's web search happened to cite a PDF — with
     the seam dark it returned links alone, and the owner had
     to go dig the manual out himself. The tiers are now:
       FOUND MANUALS — direct documents the server has
       already PROVEN it can pull: every candidate is
       fetch-probed through the same SSRF guard and offered
       only when the bytes at the address are a real PDF.
       Discovery is keyless (no paid search service, no API
       key): public search-engine result pages, the
       manufacturer's own product pages mined for their
       document links, a small set of verified manufacturer
       document-library patterns, and — when configured — the
       AI provider's web search as one more source feeding
       the same probe.
       BACKUP LINKS — shown ONLY when no pullable manual was
       found: the manufacturer's manuals/support entry point
       (from the corporate directory) and the best web pages
       the search turned up, so the user still has somewhere
       to go look. Links are never dressed up as manuals.
  2. The user PICKS from the candidate list. Nothing is ever
     auto-imported — model numbers collide across product
     lines, so a human confirms the right manual.
  3. On pick, the server DOWNLOADS the file and stores it in
     the item's Manuals permanently (owner: "links can
     change" — a stored link is not a manual; manuals are their
     own attachment kind/area, owner ruling 2026-11-03).
     Provenance — source URL + fetch date — rides the
     attachment record. The add-by-link flow (§7 of the same
     ruling) reuses this module's guard + download verbatim and
     accepts PDFs only.
  4. The outcome is notified BOTH ways through the inbox:
     saved -> "Manual found and saved to <item>'s manuals";
     none found -> "No manual found for <brand> <model>".

Downloads are SSRF-guarded: https only, every hop re-validated,
no private/loopback/link-local hosts (checked against the
resolved addresses), a redirect cap, a document content-type
requirement, and the 25 MB document cap the attachment rules
already enforce.
"""

import base64
import hashlib
import html as html_lib
import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote_plus, unquote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import (
    ALLOWED_CONTENT_TYPES,
    StorageError,
    content_matches_declared,
    storage,
)
from app.modules.billing import ai_service
from app.modules.catalog.normalize import norm_brand
from app.modules.core import inbox
from app.modules.dealers import models as dealer_models
from app.modules.inventory import attachments as inventory_attachments

MAX_REDIRECTS = 5
_DOWNLOAD_TIMEOUT_SECONDS = 30.0

_DOCUMENT_TYPES = ALLOWED_CONTENT_TYPES["document"]


class ManualError(ValueError):
    """A refusal the route turns into a 422 with friendly copy."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- candidate search ----------------------------------------------------------


def manufacturer_candidate(db: Session, brand: str) -> dict | None:
    """The manufacturer's own manuals/support entry point for
    this brand, from the platform dealer directory (seeded from
    official brand sources only). This is a PAGE candidate: it
    opens the brand's official support home — the system never
    invents a deep link to a specific document it hasn't seen."""
    key = norm_brand(brand)
    if not key:
        return None
    companies = db.scalars(
        select(dealer_models.DealerCompany).where(
            dealer_models.DealerCompany.owner_id.is_(None),
            dealer_models.DealerCompany.is_directory.is_(True),
        )
    )
    for company in companies:
        if norm_brand(company.name) != key:
            continue
        url = (company.warranty_url or "").strip() or (company.website or "").strip()
        if not url:
            return None
        return {
            "title": f"{company.name} — manuals & support",
            "source_name": company.name,
            "source_url": url,
            "file_type": "web",
            "importable": False,
        }
    return None


def web_search_configured(db: Session) -> bool:
    """The web layer rides the AI seam (owner's one-vendor
    decision, 2026-10-25): the provider's own web search is the
    site's only search, lit exactly when the AI is. There is no
    separate search provider or key to configure."""
    return ai_service.ai_configured(db)


def _ai_results(db: Session, brand: str, model: str) -> list[dict]:
    """Raw web results from the provider's web search (empty
    while the AI seam is dark, and empty when a search fails).
    Callers split them like every other source's results: PDF
    addresses feed the probe pool, pages feed the backup tier."""
    if not web_search_configured(db):
        return []
    subject = f"the owner's manual (user manual) PDF for {brand} {model}".strip()
    try:
        return ai_service.web_search(db, subject, max_results=8)
    except (ai_service.AiNotConfigured, ai_service.AiProviderError):
        return []


# -- keyless document discovery (owner re-tier, 2026-11-05) --------------------
#
# No search API, no key, nothing to configure: the server reads
# the public result pages of two general search engines, mines
# the manufacturer's own product page (found through those same
# results) for its document links, and tries a small table of
# manufacturer document-library URL patterns. Every address
# that looks like a document then faces _probe_document — the
# guarded fetch, run just far enough to prove the bytes are a
# PDF — and only proven documents are offered as found manuals.

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_FETCH_TIMEOUT_SECONDS = 10.0
_PROBE_TIMEOUT_SECONDS = 8.0
_FETCH_MAX_BYTES = 3_000_000
_MAX_PROBES = 10
_MAX_CANDIDATES = 5
_MAX_LINKS = 5

# Hosts a brand's own document library lives on. A verified
# document on one of these (or on the matched directory
# company's own domain) outranks any mirror or repository.
_MANUFACTURER_HOSTS = frozenset(
    {
        "assets.dewalt.com",
        "dewalt.com",
        "toolservicenet.com",
        "documents.milwaukeetool.com",
        "milwaukeetool.com",
        "d3cacd5apmg13r.cloudfront.net",
        "public.snapon.com",
        "snapon.com",
        "mactools.com",
        "matcotools.com",
        "tekton.com",
        "gearwrench.com",
        "cornwelltools.com",
        "harborfreight.com",
        "manuals.harborfreight.com",
        "fluke.com",
        "blackanddecker.com",
        "stanleytools.com",
        "craftsman.com",
        "makitatools.com",
        "boschtools.com",
        "ryobitools.com",
    }
)

_MANUAL_URL_TOKENS = (
    "manual",
    "instruction",
    "operator",
    "owner",
    "user_guide",
    "user-guide",
    "handbuch",
)

# A manufacturer's library also holds documents that are not
# manuals at all (tax policies, catalogs); they stay offerable
# when nothing better exists but never outrank a manual.
_NOISE_URL_TOKENS = ("tax", "privacy", "terms", "catalog")


def _fetch_text(url: str, timeout: float = _FETCH_TIMEOUT_SECONDS) -> str:
    """One plain HTML fetch for search/mining (the transport
    seam tests stub). Any failure — unreachable, non-200,
    oversize — reads as an empty page: discovery degrades,
    never raises. trust_env=False for the same reason as
    _download: an env proxy must never reroute these reads."""
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
            headers={
                "User-Agent": _BROWSER_UA,
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return ""
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _FETCH_MAX_BYTES:
                        break
                    chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")
    except httpx.HTTPError:
        return ""


def _yahoo_results(query: str) -> list[dict]:
    """Yahoo's public results page (Bing-powered, keyless).
    Result links are redirect-wrapped: the real address is the
    RU= segment, percent-encoded. Titles ride the same anchor."""
    page = _fetch_text(
        f"https://search.yahoo.com/search?p={quote_plus(query)}&n=20"
    )
    if not page:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for raw_href, inner in re.findall(
        r'href="(https://r\.search\.yahoo\.com/[^"]+)"[^>]*>(.*?)</a>',
        page,
        re.S,
    ):
        match = re.search(r"/RU=([^/]+)/RK=", raw_href)
        if not match:
            continue
        url = unquote(match.group(1))
        if not url.startswith("https://") or url in seen:
            continue
        host = urlparse(url).hostname or ""
        if "yahoo." in host or host == "search.yahoo.com":
            continue
        seen.add(url)
        title = re.sub(r"<[^>]+>", " ", html_lib.unescape(inner))
        out.append({"url": url, "title": " ".join(title.split())})
    return out


def _bing_results(query: str) -> list[dict]:
    """Bing's public results page (keyless). Result links are
    redirect-wrapped: the real address is base64url in the u=a1…
    parameter of the /ck/a URL."""
    page = _fetch_text(
        f"https://www.bing.com/search?q={quote_plus(query)}&count=20"
    )
    if not page:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for block in re.findall(r'<li class="b_algo".*?</li>', page, re.S):
        match = re.search(r'<h2><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not match:
            continue
        href = html_lib.unescape(match.group(1))
        url = href
        wrapped = re.search(r"[?&]u=a1([A-Za-z0-9_-]+)", href)
        if wrapped:
            token = wrapped.group(1)
            token += "=" * (-len(token) % 4)
            try:
                url = base64.urlsafe_b64decode(token).decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, UnicodeDecodeError):
                continue
        if not url.startswith("https://") or url in seen:
            continue
        host = urlparse(url).hostname or ""
        if "bing." in host or "microsoft." in host:
            continue
        seen.add(url)
        title = re.sub(r"<[^>]+>", " ", html_lib.unescape(match.group(2)))
        out.append({"url": url, "title": " ".join(title.split())})
    return out


def _keyless_results(brand: str, model: str) -> list[dict]:
    """Merged public-engine results for the brand + model,
    deduped by URL, Yahoo first (its index carries the
    manufacturers' document hosts directly), then Bing, then a
    second Yahoo phrasing that surfaces product pages. The
    three fetches are independent — they run in parallel so a
    slow engine doesn't stack its latency on the others."""
    subject = f"{brand} {model}".strip()
    if not subject:
        return []
    with ThreadPoolExecutor(max_workers=3) as pool:
        yahoo_first = pool.submit(_yahoo_results, f"{subject} manual pdf")
        bing = pool.submit(_bing_results, f"{subject} manual pdf")
        yahoo_second = pool.submit(
            _yahoo_results, f"{subject} instruction manual"
        )
        batches = [yahoo_first.result(), bing.result(), yahoo_second.result()]
    merged: list[dict] = []
    seen: set[str] = set()
    for batch in batches:
        for result in batch:
            if result["url"] in seen:
                continue
            seen.add(result["url"])
            merged.append(result)
    return merged


def _pattern_urls(brand: str, model: str) -> list[str]:
    """Manufacturer document-library addresses that can be
    composed from the model alone. Each is only a GUESS until
    the probe proves it — a miss is never offered. (Milwaukee's
    document CDN names operator manuals after the model; the
    file answers for 2767-20 and its siblings.)"""
    if norm_brand(brand) != "milwaukee" or not model.strip():
        return []
    slug = re.sub(r"[^a-z0-9]+", "_", model.strip().lower()).strip("_")
    if not slug:
        return []
    return [
        "https://d3cacd5apmg13r.cloudfront.net/userfiles/ad/documents/"
        f"milwaukee_{slug}_user_manual.pdf"
    ]


def _mine_page(url: str) -> list[str]:
    """The PDF addresses a page carries — hrefs and embedded
    JSON alike (the manufacturers' product pages list their
    instruction manuals exactly this way). The address itself
    is judged by the SSRF guard before a byte moves."""
    try:
        assert_safe_url(url)
    except ManualError:
        return []
    page = _fetch_text(url)
    if not page:
        return []
    cleaned = page.replace("\\/", "/").replace('\\"', '"')
    out: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r'https://[^\s"\'<>\\]+?\.pdf(?:\?[^\s"\'<>\\]*)?', cleaned):
        candidate = html_lib.unescape(raw).rstrip(".,);]")
        if candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def _probe_document(url: str) -> dict | None:
    """Prove an address holds a real PDF, using the import
    guard's own discipline: https + public hosts re-validated
    on EVERY redirect hop, capped hops — but the stream stops
    the moment the first bytes decide. Returns {"size_bytes"}
    (None size when the source doesn't say) or None when the
    address is anything but a reachable PDF. The transport
    seam tests stub."""
    current = url
    try:
        with httpx.Client(
            timeout=_PROBE_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": _BROWSER_UA},
        ) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                assert_safe_url(current)
                with client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            return None
                        current = str(httpx.URL(current).join(location))
                        continue
                    if response.status_code != 200:
                        return None
                    size: int | None = None
                    raw_length = response.headers.get("content-length")
                    if raw_length and raw_length.isdigit():
                        size = int(raw_length)
                    head = b""
                    for chunk in response.iter_bytes():
                        head += chunk
                        if len(head) >= 5:
                            break
                    if head[:5] == b"%PDF-":
                        return {"size_bytes": size}
                    return None
    except (httpx.HTTPError, ManualError, OSError):
        return None
    return None


def _is_pdf_url(url: str) -> bool:
    return url.split("?")[0].lower().endswith(".pdf")


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _manufacturer_hosts(db: Session, brand: str) -> set[str]:
    """The static document-library hosts plus the matched
    directory company's own domains for this brand."""
    hosts = set(_MANUFACTURER_HOSTS)
    key = norm_brand(brand)
    if key:
        companies = db.scalars(
            select(dealer_models.DealerCompany).where(
                dealer_models.DealerCompany.owner_id.is_(None),
                dealer_models.DealerCompany.is_directory.is_(True),
            )
        )
        for company in companies:
            if norm_brand(company.name) != key:
                continue
            for raw in (company.website or "", company.warranty_url or ""):
                host = _host_of(raw.strip())
                if host:
                    hosts.add(host)
                    if host.startswith("www."):
                        hosts.add(host[4:])
    return hosts


def _candidate_score(url: str, title: str, model: str, hosts: set[str]) -> int:
    """Probe order: the manufacturer's own library first, then
    addresses naming the model, then addresses naming
    themselves manuals, then everything else."""
    host = _host_of(url)
    score = 0
    if host in hosts or any(host.endswith("." + h) for h in hosts):
        score += 100
    haystack = f"{url} {title}".lower()
    model_key = re.sub(r"[^a-z0-9]+", "", (model or "").lower())
    if model_key and model_key in re.sub(r"[^a-z0-9]+", "", haystack):
        score += 40
    if any(token in haystack for token in _MANUAL_URL_TOKENS):
        score += 20
    if any(token in haystack for token in _NOISE_URL_TOKENS):
        score -= 60
    return score


def _squash(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _display_title(title: str, url: str, host: str) -> str:
    """The label a result is offered under. Engine anchors for
    documents are breadcrumb strings ("host https://host › A ›
    B") — noise; a document's own filename is the honest label.
    Clean page titles survive; everything else falls back to
    the filename, then the host."""
    cleaned = " ".join((title or "").split())
    if " https://" in cleaned:
        cleaned = cleaned.split(" https://")[0].strip()
    if "›" in cleaned:
        cleaned = cleaned.split("›")[0].strip()
    if _is_pdf_url(url):
        filename = unquote(
            urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        )
        if not cleaned or cleaned == host or len(cleaned) < 4:
            return filename or host
        if cleaned.lower() in host or host.startswith(cleaned.lower()):
            return filename or cleaned
        return cleaned
    return cleaned or host


def _passes_relevance(
    url: str, title: str, brand: str, model: str, hosts: set[str]
) -> bool:
    """May a VERIFIED document be offered as this item's manual?
    The manufacturer's own library always may (the user picks
    from its real documents). Anywhere else, the address or its
    title must actually relate to the item — the full model
    token, or the brand together with a manual word. A form
    that merely shares a number with the model (the "999"
    mutual-fund PDF a nonsense search surfaced in production
    proof) is not a manual for anything here."""
    host = _host_of(url)
    if host in hosts or any(host.endswith("." + h) for h in hosts):
        return True
    haystack = _squash(f"{url} {title}")
    model_key = _squash(model)
    if model_key:
        if model_key in haystack:
            return True
        # The family stem counts too (manufacturers and the
        # repositories alike file the DCF891B's manual under
        # DCF891). But brand + a manual word alone does NOT —
        # with a model in hand, a same-brand manual for a
        # DIFFERENT model is a wrong manual (production proof,
        # 2026-11-05: a "DCS354, DCS356" repository PDF was
        # offered for a DCF891B on exactly that pass).
        return (
            len(model_key) >= 5
            and model_key[-1].isalpha()
            and model_key[:-1] in haystack
        )
    brand_key = _squash(norm_brand(brand))
    if brand_key and brand_key in haystack:
        lowered = f"{url} {title}".lower()
        if any(token in lowered for token in _MANUAL_URL_TOKENS):
            return True
    return False


def search_manuals(db: Session, brand: str, model: str) -> dict:
    """One full manual search, re-tiered (owner, 2026-11-05):
    {"candidates": [proven, pullable PDF manuals],
     "links": [backup web pages for when there are none]}.

    Discovery merges the keyless engines, the AI web search
    (when configured), manufacturer product-page mining and
    the pattern table; every document address faces the probe
    before it can be offered, best first."""
    brand = (brand or "").strip()
    model = (model or "").strip()
    hosts = _manufacturer_hosts(db, brand)

    pdf_pool: list[dict] = []
    page_pool: list[dict] = []
    seen_pdf: set[str] = set()
    seen_page: set[str] = set()

    def absorb(results: list[dict]) -> None:
        for result in results:
            url = result["url"]
            title = result.get("title", "")
            if _is_pdf_url(url):
                if url not in seen_pdf:
                    seen_pdf.add(url)
                    pdf_pool.append({"url": url, "title": title})
            elif url not in seen_page:
                seen_page.add(url)
                page_pool.append({"url": url, "title": title})

    for url in _pattern_urls(brand, model):
        if url not in seen_pdf:
            seen_pdf.add(url)
            pdf_pool.append({"url": url, "title": ""})

    results = _keyless_results(brand, model)
    absorb(results)
    absorb(_ai_results(db, brand, model))

    # Mine the best manufacturer pages the search surfaced —
    # their own document lists are where the exact manual
    # (the owner's DeWalt NA537404 class) actually lives. A
    # mined document earns its place ONLY by naming the model
    # in its own address: the page the engines surfaced can be
    # a sibling product's, and its manuals are not this item's
    # (production proof, 2026-11-05: a DeWalt search mined an
    # oscillating-tool page and offered its DCS354 manual).
    mined_pages = 0
    model_key = _squash(model)
    # Manufacturers name shared manuals by the family, not the
    # variant: the DCF891B's own manual is "…_DCF891_DCF892_…".
    # A trailing variant letter may drop for mined documents.
    mined_keys = [model_key] if model_key else []
    if len(model_key) >= 5 and model_key[-1].isalpha():
        mined_keys.append(model_key[:-1])
    brand_key = _squash(norm_brand(brand))
    for result in results:
        if mined_pages >= 2:
            break
        if _is_pdf_url(result["url"]):
            continue
        host = _host_of(result["url"])
        if host not in hosts and not any(
            host.endswith("." + h) for h in hosts
        ):
            continue
        mined_pages += 1
        for url in _mine_page(result["url"]):
            squashed = _squash(url)
            if mined_keys:
                if not any(key in squashed for key in mined_keys):
                    continue
            elif brand_key and brand_key not in squashed:
                continue
            if url not in seen_pdf:
                seen_pdf.add(url)
                pdf_pool.append({"url": url, "title": ""})

    ranked = sorted(
        pdf_pool,
        key=lambda entry: -_candidate_score(
            entry["url"], entry["title"], model, hosts
        ),
    )
    # Gate first (cheap), then probe the survivors in parallel —
    # the probes are independent fetches and sequential probing
    # stacked their latency (35 s searches in production proof).
    gated = [
        entry
        for entry in ranked
        if _passes_relevance(entry["url"], entry["title"], brand, model, hosts)
    ][:_MAX_PROBES]
    with ThreadPoolExecutor(max_workers=5) as pool:
        probes = list(pool.map(_probe_document, [e["url"] for e in gated]))
    if gated and all(probe is None for probe in probes):
        # Nothing verified — one slower second pass over the
        # best few before answering "none": document CDNs have
        # transient slow answers, and an honest "no manual"
        # should survive a retry (production proof, 2026-11-05:
        # Milwaukee's own manual vanished for one search this
        # way).
        for index, entry in enumerate(gated[:3]):
            probes[index] = _probe_document(entry["url"])
    candidates: list[dict] = []
    for entry, probe in zip(gated, probes):
        if probe is None:
            continue
        host = _host_of(entry["url"])
        candidates.append(
            {
                "title": _display_title(entry["title"], entry["url"], host),
                "source_name": host,
                "source_url": entry["url"],
                "file_type": "pdf",
                "importable": True,
                "size_bytes": probe["size_bytes"],
            }
        )
        if len(candidates) >= _MAX_CANDIDATES:
            break

    links: list[dict] = []
    manufacturer = manufacturer_candidate(db, brand)
    if manufacturer is not None:
        links.append(manufacturer)
    for entry in page_pool:
        if len(links) >= _MAX_LINKS:
            break
        host = _host_of(entry["url"])
        links.append(
            {
                "title": _display_title(entry["title"], entry["url"], host),
                "source_name": host,
                "source_url": entry["url"],
                "file_type": "web",
                "importable": False,
            }
        )
    return {"candidates": candidates, "links": links}


def locate(db: Session, user, kind: str, item) -> dict:
    """Run one manual search for an item: proven candidates +
    the backup links + the outcome rules. A completed search
    with no pullable manual sends the "No manual found" inbox
    notice (owner addendum); the per-lookup credit price
    (operator-set, default 0) is charged only because the
    search COMPLETED — a search that raises charges nothing."""
    ai_service.begin_usage_capture()
    found = search_manuals(db, item.brand or "", item.model or "")
    charged = ai_service.charge_for(
        db,
        user.id,
        "manual_lookup",
        subject=(
            f"{item.brand or ''} {item.model or ''} ({item.name})".strip()
        ),
    )
    if not found["candidates"]:
        inbox.create_notification(
            db,
            user.id,
            kind=inbox.KIND_MANUAL_NOT_FOUND,
            title="No manual found",
            body=(
                f"No manual found for {item.brand} {item.model}".strip()
                + f" ({item.name})."
            ),
            data={"item_kind": kind, "item_id": str(item.id)},
        )
    return {**found, "charged": charged}


def find_manuals(db: Session, user, brand: str, model: str) -> dict:
    """The same search for something that has no item yet —
    the Add wizard, mid-flow: brand + model come from the
    draft, the pick is remembered, and the ordinary import
    endpoint pulls it the moment the item exists. No inbox
    notice (there is no item to point it at)."""
    ai_service.begin_usage_capture()
    found = search_manuals(db, brand, model)
    charged = ai_service.charge_for(
        db, user.id, "manual_lookup", subject=f"{brand} {model}".strip()
    )
    return {**found, "charged": charged}


# -- download + import -----------------------------------------------------------


def _host_ips(host: str) -> list[str]:
    """Resolve a host to its IPs (wrapped so tests can stub the
    resolver; the SSRF guard judges THESE addresses)."""
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


def assert_safe_url(url: str) -> None:
    """SSRF guard, applied to the target AND every redirect hop:
    https only, a real host, and every resolved address public."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ManualError("Manuals can only be fetched over https.")
    host = parsed.hostname or ""
    if not host or host == "localhost":
        raise ManualError("That address isn't a public website.")
    try:
        ips = _host_ips(host)
    except OSError as exc:
        raise ManualError(f"Couldn't resolve {host}.") from exc
    if not ips:
        raise ManualError(f"Couldn't resolve {host}.")
    for raw in ips:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise ManualError(f"Couldn't verify {host}.") from exc
        if not address.is_global:
            raise ManualError("That address isn't a public website.")


def _download(url: str) -> tuple[bytes, str]:
    """Fetch a document with the guards on: manual redirect
    loop (each hop re-validated), size-capped streaming. Returns
    (bytes, content_type). The transport seam tests stub."""
    current = url
    cap = inventory_attachments.DOCUMENT_MAX_BYTES
    # trust_env=False is load-bearing: an env-configured proxy
    # would resolve DNS itself and silently defeat the SSRF
    # guard above (and httpx crashes parsing some proxy URLs).
    # This client only ever talks to URLs the guard approved.
    # The browser UA is presentation only — several manufacturer
    # document hosts refuse the default client signature; every
    # guard check above is untouched by it.
    with httpx.Client(
        timeout=_DOWNLOAD_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": _BROWSER_UA},
    ) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            assert_safe_url(current)
            with client.stream("GET", current) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise ManualError("The source redirected nowhere.")
                    current = str(
                        httpx.URL(current).join(location)
                    )
                    continue
                if response.status_code != 200:
                    raise ManualError(
                        f"The source answered HTTP {response.status_code}."
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
                    if total > cap:
                        raise ManualError(
                            "That file is larger than the 25 MB document limit."
                        )
                    chunks.append(chunk)
                return b"".join(chunks), content_type
    raise ManualError("Too many redirects.")


def _filename_for(url: str, item, content_type: str) -> str:
    path_name = urlparse(url).path.rsplit("/", 1)[-1]
    if path_name and "." in path_name:
        return storage.safe_filename(path_name)
    ext = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "text/plain": ".txt",
    }.get(content_type, ".pdf")
    base = f"{item.brand} {item.model} manual".strip() or f"{item.name} manual"
    return storage.safe_filename(base) + ext


def import_manual(
    db: Session,
    user,
    kind: str,
    item,
    source_url: str,
    source_name: str = "",
) -> tuple[dict, bool]:
    """Download the picked manual into the item's Manuals.

    Returns (attachment, created): created False when the item
    already holds this manual (same source URL, or the same
    bytes under another URL) — a friendly no-op, not an error.
    Raises ManualError for anything that can't be stored."""
    existing = [
        entry
        for entry in item.attachments or []
        if isinstance(entry, dict) and entry.get("origin") == "manual"
    ]
    for entry in existing:
        if entry.get("source_url") == source_url:
            return entry, False

    data, content_type = _download(source_url)
    if content_type not in _DOCUMENT_TYPES:
        if data[:5] == b"%PDF-":
            content_type = "application/pdf"
        else:
            raise ManualError(
                "That link didn't lead to a document file "
                f"(got {content_type or 'an unknown type'})."
            )
    elif not content_matches_declared(content_type, data[:512]):
        # The source CLAIMED a document type its bytes contradict
        # (deep audit F4-06 parity with the upload attach sniff):
        # PDF bytes under a wrong label are still a PDF; anything
        # else is refused rather than stored under a false type.
        if data[:5] == b"%PDF-":
            content_type = "application/pdf"
        else:
            raise ManualError(
                "That link didn't lead to a document file "
                f"(got {content_type or 'an unknown type'})."
            )
    digest = hashlib.sha256(data).hexdigest()
    for entry in existing:
        if entry.get("content_sha256") == digest:
            return entry, False

    filename = _filename_for(source_url, item, content_type)
    key = storage.object_key(
        str(user.id), str(item.id), "manual", filename, collection=kind
    )
    try:
        stored = storage.put_bytes(key, data, content_type)
    except StorageError as exc:
        raise ManualError(str(exc)) from exc
    attachment = {
        "key": stored.key,
        "filename": filename,
        "kind": "manual",
        "content_type": content_type,
        "size_bytes": stored.size_bytes,
        "uploaded_at": _now().isoformat(),
        "origin": "manual",
        "source_url": source_url,
        "source_name": source_name or (urlparse(source_url).hostname or ""),
        "fetched_at": _now().isoformat(),
        "content_sha256": digest,
    }
    item.attachments = [*(item.attachments or []), attachment]
    db.commit()
    db.refresh(item)
    inbox.create_notification(
        db,
        user.id,
        kind=inbox.KIND_MANUAL_SAVED,
        title="Manual saved",
        body=f"Manual found and saved to {item.name}'s manuals.",
        data={"item_kind": kind, "item_id": str(item.id)},
    )
    return attachment, True


def import_manual_from_link(
    db: Session, user, kind: str, item, raw_url: str
) -> tuple[dict, bool]:
    """Add a manual by pasting a link (owner ruling 2026-11-03):
    the user pastes an address (a scheme is optional — a bare
    "www.example.com/x.pdf" is read as https), the server
    downloads it through the SAME SSRF guard and capped download
    the finder uses, and — PDFs only, judged by the magic bytes,
    never the label — stores the BYTES as the item's manual
    (never a hotlink). Any failure raises ManualError and files
    NOTHING. Returns (attachment, created) with import_manual's
    dedupe semantics: the same source URL, or the same bytes
    under another URL, is a friendly no-op."""
    url = (raw_url or "").strip()
    if not url:
        raise ManualError("Paste the manual's web address first.")
    if "://" not in url:
        url = "https://" + url
    existing = [
        entry
        for entry in item.attachments or []
        if isinstance(entry, dict) and entry.get("origin") == "manual"
    ]
    for entry in existing:
        if entry.get("source_url") == url:
            return entry, False

    data, _content_type = _download(url)
    if data[:5] != b"%PDF-":
        raise ManualError(
            "That link didn't lead to a PDF manual — the address "
            "must point straight at a PDF file."
        )
    digest = hashlib.sha256(data).hexdigest()
    for entry in existing:
        if entry.get("content_sha256") == digest:
            return entry, False

    filename = _filename_for(url, item, "application/pdf")
    if not filename.lower().endswith(".pdf"):
        # The bytes are a PDF whatever the address called the
        # file — the stored name says so.
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        filename = f"{stem}.pdf"
    key = storage.object_key(
        str(user.id), str(item.id), "manual", filename, collection=kind
    )
    try:
        stored = storage.put_bytes(key, data, "application/pdf")
    except StorageError as exc:
        raise ManualError(str(exc)) from exc
    attachment = {
        "key": stored.key,
        "filename": filename,
        "kind": "manual",
        "content_type": "application/pdf",
        "size_bytes": stored.size_bytes,
        "uploaded_at": _now().isoformat(),
        "origin": "manual",
        "source_url": url,
        "source_name": urlparse(url).hostname or "",
        "fetched_at": _now().isoformat(),
        "content_sha256": digest,
    }
    item.attachments = [*(item.attachments or []), attachment]
    db.commit()
    db.refresh(item)
    inbox.create_notification(
        db,
        user.id,
        kind=inbox.KIND_MANUAL_SAVED,
        title="Manual saved",
        body=f"Manual saved from the link to {item.name}'s manuals.",
        data={"item_kind": kind, "item_id": str(item.id)},
    )
    return attachment, True
