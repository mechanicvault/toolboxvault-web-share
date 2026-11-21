"""The catalog agent (lookup rebuild Phase 3, 2026-11-20).

Replaces the fixed fetch-and-parse walk with an evidence-
gathering loop: a driver model with a small set of
brand-agnostic tools (open a page, read one section, read or
replay a recorded data response, reload for another slice of
a rotating list, search the maker's site, open a piece's own
page, check the library, submit). The driver proposes; the
referee (referee.py, plain code) decides what is proven;
only a referee-verified result is written to the library as
verified — everything else lands as a candidate or stays a
labeled partial.

The rules the driver works under are Ryan's: the user gives
a part number, never a web address; facts come only from
pages and responses the system actually opened; retail
prices only (internal PRICE: tags are stripped at the
evidence layer before the model can see them); a labeled
partial is a correct outcome and an invented piece is a
failure.

Runs behind the operator flag `catalog.agent_enabled`
(default off) and only on the full-import path — the quick
path keeps today's behavior until Phase 4's jobs land.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.modules.billing import ai_service, entitlements
from app.modules.catalog import evidence, grounded, library, referee
from app.modules.catalog.normalize import norm_model

_MAX_STEPS = 40
_MAX_STALE_SUBMITS = 2


def _clean_str(value) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _clean_num(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("$", "").replace(",", "").strip())
        except ValueError:
            return None
    return None


def _sanitize_proposal(proposal: dict) -> dict:
    """Coerce a model-written proposal into the shapes the
    referee and the result builder rely on. Model output is
    untrusted typing: a live run proposed photos=true and
    crashed the result builder (2026-11-20). Wrong-typed
    values are dropped, never guessed at — the referee then
    judges the honest remainder."""
    if not isinstance(proposal, dict):
        return {}
    product_in = proposal.get("product")
    product_in = product_in if isinstance(product_in, dict) else {}
    product: dict = {}
    for key in ("brand", "model", "name", "category", "size", "description"):
        cleaned = _clean_str(product_in.get(key))
        if cleaned is not None:
            product[key] = cleaned
    msrp = _clean_num(product_in.get("msrp"))
    if msrp is not None:
        product["msrp"] = msrp
    photos_in = product_in.get("photos")
    product["photos"] = (
        [p for p in photos_in if isinstance(p, str)] if isinstance(photos_in, list) else []
    )
    specs_in = product_in.get("specs")
    product["specs"] = specs_in if isinstance(specs_in, dict) else {}
    for key in ("warranty_type", "warranty_terms", "source_name", "source_url"):
        cleaned = _clean_str(product_in.get(key))
        if cleaned is not None:
            product[key] = cleaned
    months = _clean_num(product_in.get("warranty_months"))
    if months is not None:
        product["warranty_months"] = int(months)
    pieces: list = []
    pieces_in = proposal.get("pieces")
    if isinstance(pieces_in, list):
        for entry in pieces_in:
            if not isinstance(entry, dict):
                continue
            piece: dict = {}
            for key in ("name", "model"):
                cleaned = _clean_str(entry.get(key))
                if cleaned is not None:
                    piece[key] = cleaned
            price = _clean_num(entry.get("msrp"))
            if price is not None:
                piece["msrp"] = price
            image = _clean_str(entry.get("image_url"))
            if image is not None:
                piece["image_url"] = image
            qty = _clean_num(entry.get("qty"))
            if qty is not None:
                piece["qty"] = int(qty)
            source = _clean_str(entry.get("source"))
            if source is not None:
                piece["source"] = source
            evidence_in = entry.get("evidence")
            if isinstance(evidence_in, list):
                cleaned_evidence = []
                for item in evidence_in:
                    if isinstance(item, dict):
                        cleaned_evidence.append(
                            {
                                "id": _clean_str(item.get("id")) or "",
                                "quote": _clean_str(item.get("quote")) or "",
                            }
                        )
                    elif isinstance(item, str):
                        cleaned_evidence.append(item)
                piece["evidence"] = cleaned_evidence
            pieces.append(piece)
    stated = _clean_num(proposal.get("stated_piece_count"))
    return {
        "product": product,
        "is_set": proposal.get("is_set") is True,
        "stated_piece_count": int(stated) if stated is not None else None,
        "makeup": proposal.get("makeup") if isinstance(proposal.get("makeup"), list) else [],
        "pieces": pieces,
        "status": proposal.get("status"),
    }

_CROSS_SELL_KEYWORDS = ("similar", "related", "recommended", "you may also", "customers also", "also bought")
_CONTENTS_KEYWORDS = ("set details", "set contents", "contents", "includes", "included", "in the box")

_DRIVER_INSTRUCTIONS = """You find the complete, verified catalog record for ONE tool part number, for a tool-inventory app used by mechanics.

RULES
1. Every fact you report must come from evidence you opened with a tool. Cite the evidence in each piece's evidence list. Your own knowledge is never evidence.
2. The part number must match exactly, including dots, dashes and suffixes (MUP65.5MMR != MUP655MMR). If no page shows it as the product's own number, submit status not_found. Never substitute a similar product.
3. Retail price only. Ignore any internal price levels, dealer, net, or tag-style prices. Leave price empty rather than guess.
4. Sets: find the stated piece count and the described makeup first. Then gather pieces until your confirmed list matches both. Prefer, in order: recorded data responses that hold the list; the section that IS the set contents; replaying a data response / reloading for another slice of a rotating list (keep going until 3 tries in a row add nothing new); the site's own search for the specific missing pieces the makeup predicts.
5. Pieces may only come from the set-contents section (or a piece page that says it belongs to this set). Never take pieces from similar / related / recommended rails, even if prices look right. Add-on products the page advertises go in addons, never in pieces.
6. When the referee returns gaps, work only on those gaps. Stop when the referee says verified, when two submits in a row confirm nothing new, or when told to stop. A labeled partial result is a correct outcome; an invented piece is a failure.
7. Be economical: read sections, not whole pages; open pieces in parallel batches."""

_TOOLS = [
    {
        "type": "web_search",
    },
    {
        "type": "function",
        "name": "open_page",
        "description": "Open a product page in a real browser. Returns a compact page map: title, stated piece count, structured products, labeled sections with card counts and samples, and the recorded data responses (ids R1, R2, ...). Sections get ids S1, S2, ...",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "read_section",
        "description": "Read one section of the last opened page in full: every card's text.",
        "parameters": {
            "type": "object",
            "properties": {"section_id": {"type": "string"}},
            "required": ["section_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "read_data_response",
        "description": "Read a recorded data response (by id), or the array at a path inside it.",
        "parameters": {
            "type": "object",
            "properties": {
                "response_id": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["response_id", "path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "replay_data_response",
        "description": "Re-request a recorded data response directly (fast, no page render) — the way to get another slice of a rotating list. Returns how many NEW part numbers it added.",
        "parameters": {
            "type": "object",
            "properties": {"response_id": {"type": "string"}},
            "required": ["response_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "interact",
        "description": "Reload the current page (a fresh render — another slice of any rotating list) and report which cards in each section are new.",
        "parameters": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["reload"]}},
            "required": ["action"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "site_search",
        "description": "Search one site (the maker's own search via web search) for a part number or product.",
        "parameters": {
            "type": "object",
            "properties": {
                "site": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["site", "query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "open_piece",
        "description": "Open a piece's own product page (found via site_search or a card link): confirms the part number and gives its retail price, photo, brand and drive.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "read_feed",
        "description": "Read the maker's structured data feed for this part number when one exists (Mac Tools today): retail fields and the set's piece list, returned as citable evidence. Try it before the open-page walk for supported brands.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "library_lookup",
        "description": "What the site's own library already holds for this brand + part number (status and trust included), and which sets contain a piece.",
        "parameters": {
            "type": "object",
            "properties": {"piece_model": {"type": "string"}},
            "required": ["piece_model"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "submit",
        "description": "Hand a proposal to the referee. It answers verified, or partial with the exact gaps. Proposal: {status: found|not_found, product: {brand, model, name, category, size, msrp, description, photos, specs, warranty{type,months,terms}}, is_set, stated_piece_count, makeup: [{type, drive, size_from, size_to, qty}], pieces: [{model, name, msrp, image_url, qty, source, evidence: [{id, quote}]}], addons: [...]}",
        "parameters": {
            "type": "object",
            "properties": {"proposal": {"type": "object"}},
            "required": ["proposal"],
            "additionalProperties": False,
        },
        "strict": False,
    },
]


def agent_enabled(db: Session) -> bool:
    value = (entitlements.get_setting(db, "catalog.agent_enabled", "") or "")
    return value.strip().lower() in ("on", "true", "1", "yes")


# -- seams (stubbed in tests) -------------------------------------


def _load_page(url: str) -> tuple[str, list, list, str]:
    """(html, media, recordings, view) for one URL: the
    recorded browser render when available, the raw download
    as fallback — the same discipline as the old walk. `view`
    says which one the agent is actually looking at, so a
    degraded read is visible in the tool result instead of
    silently thinner (the 2026-11-20 smoke run: the recorded
    render had never worked and every page arrived raw)."""
    url = grounded.validate_page_url(url)
    try:
        from app.modules.catalog import rendered

        if rendered.rendered_enabled():
            html, media, recordings = rendered.render_page_recorded(url)
            return html, media, recordings, "rendered"
    except Exception:
        pass
    html = grounded._fetch_html(url)
    return html, [], [], "raw"


def _fetch_url(url: str) -> tuple[str, str]:
    """(content_type, body) for replaying a recorded data
    response directly. Safety-checked like any fetch."""
    import httpx

    url = grounded.validate_page_url(url)
    response = httpx.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"},
        timeout=20.0,
        follow_redirects=True,
    )
    return (response.headers.get("content-type", ""), response.text)


def _piece_page(url: str) -> dict:
    """The parsed product page for one piece (grounded's
    reader — the facts, never the AI's word)."""
    return grounded.fetch_product_page(url)


# -- the run -------------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z]*\d[A-Za-z0-9.\-]{2,}")


def _tokens(text: str) -> set[str]:
    return {
        norm_model(match.group(0))
        for match in _TOKEN_RE.finditer(text or "")
        if any(ch.isdigit() for ch in match.group(0))
    }


class _Run:
    def __init__(self, db: Session, *, brand: str, model: str, upc: str):
        self.db = db
        self.brand = brand
        self.model = model
        self.upc = upc
        self.recordings: list[dict] = []  # each gains an "rid"
        self.pages: dict[str, dict] = {}  # url -> {html, map}
        self.sections: dict[str, dict] = {}  # S<n> -> section record
        self.current_url: str | None = None
        self.card_union: dict[str, set[str]] = {}  # section id -> card texts
        self.piece_pages: dict[str, dict] = {}
        self.best: dict | None = None  # best (proposal, verdict)
        self.best_confirmed: set[str] = set()
        self.stale_submits = 0
        self.verdict: dict | None = None

    # -- evidence bookkeeping

    def _store(self, url: str, kind: str, section: str | None, payload: dict):
        try:
            evidence.store_evidence(
                self.db,
                brand=self.brand,
                model=self.model,
                url=url,
                kind=kind,
                section=section,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 — bookkeeping never sinks a run
            self.db.rollback()

    def _register_recordings(self, recordings: list[dict]) -> list[dict]:
        out = []
        for rec in recordings:
            rec = dict(rec)
            rec["rid"] = f"R{len(self.recordings) + 1}"
            self.recordings.append(rec)
            out.append(rec)
        return out

    def _section_record(self, url: str, section: dict) -> str:
        sid = f"S{len(self.sections) + 1}"
        self.sections[sid] = {"url": url, **section}
        return sid

    # -- tools

    def tool_open_page(self, args: dict) -> str:
        url = str(args.get("url") or "")
        html, _media, recordings, view = _load_page(url)
        registered = self._register_recordings(recordings)
        page_map = evidence.build_page_map(
            html,
            recordings=[
                {"url": r["url"], "status": r["status"], "arrays": r["arrays"]}
                for r in registered
            ],
        )
        self.pages[url] = {"html": html, "map": page_map}
        self.current_url = url
        self._store(url, "page_map", None, page_map)
        for rec in registered:
            self._store(rec["url"], "data_response", None, {"arrays": rec["arrays"]})
        sections_out = []
        for section in page_map["sections"]:
            sid = self._section_record(url, section)
            self.card_union.setdefault(sid, set()).update(
                section.get("samples") or []
            )
            sections_out.append({"id": sid, **section})
        result = {
            "title": page_map["title"],
            "stated_piece_count": page_map["stated_piece_count"],
            "jsonld_products": page_map["jsonld_products"],
            "sections": sections_out,
            "data_responses": [
                {"id": r["rid"], "url": r["url"], "arrays": r["arrays"]}
                for r in registered
            ],
            "view": view,
        }
        if view != "rendered":
            result["note"] = (
                "Browser view unavailable for this page — you are "
                "reading the raw download: tab content and data "
                "responses are missing. Facts here are thinner; "
                "prefer another source or the brand feed."
            )
        return json.dumps(result)[:12_000]

    def tool_read_section(self, args: dict) -> str:
        sid = str(args.get("section_id") or "")
        section = self.sections.get(sid)
        if section is None:
            return json.dumps({"error": f"unknown section {sid}"})
        page = self.pages.get(section["url"]) or {}
        html = page.get("html") or ""
        # Re-derive the section's full card list from the DOM.
        full = evidence.build_page_map(html)
        cards: list[str] = []
        for candidate in full["sections"]:
            if candidate["keyword"] == section["keyword"] and candidate[
                "heading"
            ] == section["heading"]:
                cards = candidate.get("samples") or []
                break
        self.card_union.setdefault(sid, set()).update(cards)
        return json.dumps(
            {"section": sid, "keyword": section["keyword"], "cards": cards}
        )[:12_000]

    def tool_read_data_response(self, args: dict) -> str:
        rid = str(args.get("response_id") or "")
        path = str(args.get("path") or "$")
        for rec in self.recordings:
            if rec["rid"] == rid:
                recorder = evidence.ResponseRecorder()
                recorder.recordings = self.recordings
                node = recorder.data_at(rec["url"], path)
                return json.dumps(node, default=str)[:12_000]
        return json.dumps({"error": f"unknown response {rid}"})

    def tool_replay_data_response(self, args: dict) -> str:
        rid = str(args.get("response_id") or "")
        target = next(
            (r for r in self.recordings if r["rid"] == rid), None
        )
        if target is None:
            return json.dumps({"error": f"unknown response {rid}"})
        before = set()
        for rec in self.recordings:
            if rec["url"] == target["url"]:
                before |= _tokens(json.dumps(rec["data"], default=str))
        content_type, body = _fetch_url(target["url"])
        fresh = evidence.ResponseRecorder()
        fresh.offer(target["url"], 200, content_type, body)
        if not fresh.recordings:
            return json.dumps({"new_part_numbers": 0, "note": "replay returned no JSON"})
        registered = self._register_recordings(fresh.recordings)
        after = _tokens(json.dumps(fresh.recordings[0]["data"], default=str))
        self._store(target["url"], "data_response", None, {"arrays": fresh.recordings[0]["arrays"]})
        return json.dumps(
            {
                "new_response_id": registered[0]["rid"],
                "new_part_numbers": len(after - before),
                "arrays": fresh.recordings[0]["arrays"],
            }
        )

    def tool_interact(self, args: dict) -> str:
        if not self.current_url:
            return json.dumps({"error": "no page is open"})
        url = self.current_url
        before = {
            sid: set(texts) for sid, texts in self.card_union.items()
        }
        out = self.tool_open_page({"url": url})
        new_cards = {}
        for sid, texts in self.card_union.items():
            fresh = texts - before.get(sid, set())
            if fresh:
                new_cards[sid] = len(fresh)
        return json.dumps({"reloaded": url, "new_cards_by_section": new_cards})

    def tool_site_search(self, args: dict) -> str:
        site = str(args.get("site") or "")
        query = str(args.get("query") or "")
        results = ai_service.web_search(
            self.db, f"site:{site} {query}", max_results=8
        )
        return json.dumps(results)[:8_000]

    def tool_open_piece(self, args: dict) -> str:
        url = str(args.get("url") or "")
        page = _piece_page(url)
        target = norm_model(self.model)
        found = None
        for candidate in page.get("candidates") or []:
            if norm_model(str(candidate.get("model") or "")):
                found = candidate
                break
        if found is None:
            return json.dumps({"found": False, "url": url})
        key = norm_model(str(found.get("model") or ""))
        entry = {
            "found": True,
            "msrp": found.get("msrp"),
            "image_url": found.get("image"),
            "brand": found.get("brand"),
            "drive": None,
            "name": found.get("name"),
            "size": found.get("size"),
        }
        self.piece_pages[key] = entry
        return json.dumps({"piece": key, **entry})[:4_000]

    def tool_read_feed(self, args: dict) -> str:
        from app.modules.catalog import feeds
        from app.modules.catalog.normalize import norm_brand as _nb

        if _nb(self.brand) != "mac":
            return json.dumps({"feed": None, "note": "no feed for this brand"})
        result = feeds.mac_product(self.model)
        if result is None:
            return json.dumps({"feed": None, "note": "the feed has nothing for this part"})
        recording = {
            "url": result.get("source_url") or "",
            "status": 200,
            "arrays": [
                {
                    "path": "$.pieces",
                    "count": len(result.get("pieces") or []),
                    "keys": ["model", "msrp", "name"],
                }
            ],
            "data": {
                "fields": result.get("fields") or {},
                "pieces": result.get("pieces") or [],
            },
        }
        registered = self._register_recordings([recording])
        self._store(
            recording["url"], "data_response", None, {"arrays": recording["arrays"]}
        )
        return json.dumps(
            {
                "evidence_id": registered[0]["rid"],
                "fields": result.get("fields") or {},
                "pieces": result.get("pieces") or [],
                "photos": result.get("photos") or [],
                "specs": result.get("specs") or {},
            },
            default=str,
        )[:12_000]

    def tool_library_lookup(self, args: dict) -> str:
        result = library.library_result(
            self.db, brand=self.brand, model=self.model, upc=self.upc
        )
        piece_model = str(args.get("piece_model") or "")
        sets = library.sets_containing(self.db, piece_model) if piece_model else []
        return json.dumps(
            {
                "library": result,
                "sets_containing_piece": [
                    s["fields"].get("model") for s in sets
                ],
            },
            default=str,
        )[:8_000]

    def _evidence_texts(self) -> dict[str, str]:
        """Every evidence id this run actually produced, with
        the text behind it — the registry a proposal's quotes
        are checked against. A citation the run never produced
        is not evidence."""
        texts: dict[str, str] = {}
        for rec in self.recordings:
            texts[rec["rid"]] = json.dumps(rec["data"], default=str)
        for sid, cards in self.card_union.items():
            texts[sid] = " ".join(sorted(cards))
        for key, page in self.piece_pages.items():
            texts[f"piece:{key}"] = f"{page.get('name') or ''} {key}"
        return texts

    def tool_submit(self, args: dict) -> str:
        proposal = _sanitize_proposal(args.get("proposal") or {})
        if proposal.get("status") == "not_found":
            self.verdict = {"status": "not_found", "confirmed": []}
            return json.dumps({"verdict": "not_found"})
        # Grounding, enforced by the driver before the referee
        # sees the proposal: a piece's evidence counts only
        # when the cited id is one this run produced AND the
        # quote actually appears in it. The model cannot mint
        # evidence by citing ids or quotes that don't exist.
        registry = self._evidence_texts()
        for piece in proposal.get("pieces") or []:
            valid = []
            for entry in piece.get("evidence") or []:
                if not isinstance(entry, dict):
                    continue
                source_text = registry.get(str(entry.get("id") or ""))
                quote = " ".join(str(entry.get("quote") or "").split()).lower()
                if source_text and quote and quote in " ".join(source_text.split()).lower():
                    valid.append(entry)
            piece["evidence"] = valid
        # Contents membership comes only from what the SYSTEM
        # observed — contents-labeled sections and recorded
        # data responses — never from the proposal's own
        # source labels.
        contents_models: set[str] = set()
        cross_models: set[str] = set()
        contents_images: set[str] = set()
        for sid, section in self.sections.items():
            tokens: set[str] = set()
            for text in self.card_union.get(sid, set()):
                tokens |= _tokens(text)
            keyword = section.get("keyword") or ""
            if keyword in _CROSS_SELL_KEYWORDS:
                cross_models |= tokens
            if keyword in _CONTENTS_KEYWORDS:
                contents_models |= tokens
        for rec in self.recordings:
            contents_models |= _tokens(json.dumps(rec["data"], default=str))
        # The stated count the run's own pages announced —
        # the referee judges the proposal against the evidence,
        # not against the proposal's own claim.
        evidence_stated = None
        for page in self.pages.values():
            count = (page.get("map") or {}).get("stated_piece_count")
            if count:
                evidence_stated = max(evidence_stated or 0, int(count))
        # A brand feed that listed this product's pieces is
        # evidence of the count too (live failure, 2026-11-20:
        # a 9-piece Mac set verified as a bare product because
        # only page titles fed this floor and the agent never
        # opened a page — it read the feed and stopped).
        for rec in self.recordings:
            data = rec.get("data") or {}
            if isinstance(data, dict) and isinstance(data.get("pieces"), list):
                if data["pieces"]:
                    evidence_stated = max(
                        evidence_stated or 0, len(data["pieces"])
                    )
        verdict = referee.judge(
            proposal,
            cross_sell_models=cross_models,
            contents_models=contents_models,
            contents_images=contents_images,
            piece_pages=self.piece_pages,
            evidence_stated_count=evidence_stated,
        )
        confirmed_keys = {
            norm_model(str(p.get("model") or "")) for p in verdict["confirmed"]
        }
        if self.best is None or len(confirmed_keys) > len(self.best_confirmed):
            self.best = (proposal, verdict)
            self.stale_submits = 0
        else:
            self.stale_submits += 1
        self.best_confirmed = confirmed_keys | self.best_confirmed if self.best else confirmed_keys
        self.verdict = verdict
        result = {
            "verdict": verdict["status"],
            "confirmed": len(verdict["confirmed"]),
            "dropped": verdict["dropped"],
            "unconfirmed": verdict["unconfirmed"],
            "gaps": verdict["gaps"],
            "warnings": verdict["warnings"],
        }
        if verdict["status"] == "partial":
            # A submit is a checkpoint, not the end of the run:
            # say so in the result itself, where the driver
            # model cannot miss it (left to the instructions
            # alone, drivers stopped after one partial submit).
            result["next"] = (
                "This run is NOT over. Work the gaps above — "
                "replay data responses for more pieces, open "
                "piece pages, read the feed — then submit again "
                "with everything confirmed so far PLUS the new "
                "evidence. Stop only when verified or when the "
                "gaps honestly cannot be filled."
            )
        return json.dumps(result)[:8_000]


_HANDLERS = {
    "open_page": _Run.tool_open_page,
    "read_section": _Run.tool_read_section,
    "read_data_response": _Run.tool_read_data_response,
    "replay_data_response": _Run.tool_replay_data_response,
    "interact": _Run.tool_interact,
    "site_search": _Run.tool_site_search,
    "open_piece": _Run.tool_open_piece,
    "read_feed": _Run.tool_read_feed,
    "library_lookup": _Run.tool_library_lookup,
    "submit": _Run.tool_submit,
}


def _result_from(run: _Run, proposal: dict, verdict: dict) -> dict:
    proposal = _sanitize_proposal(proposal)
    product = proposal.get("product") or {}
    fields = {
        key: product.get(key)
        for key in ("name", "brand", "model", "category", "size", "msrp", "description")
        if product.get(key) not in (None, "")
    }
    fields.setdefault("brand", run.brand)
    fields.setdefault("model", run.model)
    specs = {}
    for spec in product.get("specs") or []:
        if isinstance(spec, dict) and spec.get("name"):
            specs[str(spec["name"])] = spec.get("value")
    warranty = product.get("warranty") or {}
    return {
        "fields": fields,
        "pieces": [
            {
                "name": piece.get("name") or "",
                "model": piece.get("model"),
                "msrp": piece.get("msrp"),
                "image_url": piece.get("image_url"),
            }
            for piece in verdict["confirmed"]
        ],
        "piece_count": proposal.get("stated_piece_count"),
        "photos": list(product.get("photos") or []),
        "specs": specs,
        "warranty_type": warranty.get("type"),
        "warranty_months": warranty.get("months"),
        "warranty_terms": warranty.get("terms"),
        "source_name": fields.get("brand") or "Catalog agent",
        "source_url": run.current_url,
        "image_url": (product.get("photos") or [None])[0],
        "ai_used": True,
        "agent_status": verdict["status"],
        "agent_gaps": verdict.get("gaps") or [],
    }


def run_agent_lookup(
    db: Session, *, brand: str = "", model: str = "", upc: str = ""
) -> dict | None:
    """One agent run for a part number. Returns the grounded
    result shape (with agent_status / agent_gaps), or None
    when the AI seam isn't configured — the caller falls back
    to the old walk, so the agent can never make a lookup
    worse than today."""
    if not ai_service.ai_configured(db):
        return None
    run = _Run(db, brand=brand, model=model, upc=upc)
    hints = library.library_result(db, brand=brand, model=model, upc=upc)
    opening = {
        "role": "user",
        "content": (
            f"TARGET: brand={brand!r} part_number={model!r} upc={upc!r}\n"
            f"Library hints (unproven unless status=verified): "
            f"{json.dumps(hints, default=str)[:3000] if hints else 'none'}\n"
            "Find the manufacturer's product page first (web search), "
            "open it, and work the set until the referee verifies it "
            "or the gaps are honestly unfillable. Then submit."
        ),
    }
    input_items: list = [opening]
    for _step in range(_MAX_STEPS):
        body = ai_service.run_agent_turn(
            db,
            instructions=_DRIVER_INSTRUCTIONS,
            input_items=input_items,
            tools=_TOOLS,
        )
        outputs = [
            item
            for item in (body.get("output") or [])
            if isinstance(item, dict) and item.get("type") == "function_call"
        ]
        if not outputs:
            break
        input_items.extend(body.get("output") or [])
        for call in outputs:
            name = call.get("name") or ""
            try:
                args = json.loads(call.get("arguments") or "{}")
            except ValueError:
                args = {}
            handler = _HANDLERS.get(name)
            if handler is None:
                result_text = json.dumps({"error": f"unknown tool {name}"})
            else:
                try:
                    result_text = handler(run, args)
                except Exception as exc:  # noqa: BLE001 — a failed tool is data
                    result_text = json.dumps({"error": str(exc)[:300]})
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.get("call_id"),
                    "output": result_text,
                }
            )
        if run.verdict and run.verdict.get("status") in ("verified", "not_found"):
            break
        if run.stale_submits >= _MAX_STALE_SUBMITS:
            break
    if run.verdict and run.verdict.get("status") == "not_found":
        return {
            "fields": {},
            "pieces": [],
            "piece_count": None,
            "photos": [],
            "specs": {},
            "warranty_type": None,
            "warranty_months": None,
            "warranty_terms": None,
            "source_name": None,
            "source_url": None,
            "image_url": None,
            "ai_used": True,
            "agent_status": "not_found",
            "agent_gaps": [],
        }
    if run.best is None:
        return None
    proposal, verdict = run.best
    if not verdict["confirmed"] and not (proposal.get("product") or {}).get("name"):
        return None
    return _result_from(run, proposal, verdict)
