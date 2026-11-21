"""The referee (lookup rebuild Phase 2, 2026-11-20).

Plain code — no AI — that decides whether a proposed set
record is PROVEN. The agent proposes; the referee disposes.
It is the only thing that can mark a set verified, and it
exists because the pre-rebuild pipeline certified its own
output: the SBUPM246V walk harvested 12 real sockets plus 6
Similar-Products impact wrenches, passed the "half priced"
bar, and wrote the contaminated list into the library as
truth.

Checks (the plan's section 6, with the review amendments):
- count: confirmed pieces must equal the stated count;
- makeup: the described makeup (10 standard 10–19mm, 10
  deep, 3 extensions, 1 adapter) must be filled — but ONLY
  when the extracted groups sum to the stated count; a
  makeup that doesn't add up is ignored (the count check is
  pure code; the makeup extraction is AI-supplied) and the
  record is flagged;
- no cross-sell: a piece that appears in a similar /
  related / recommended section is dropped unless it also
  appears in the contents section;
- own-page proof: where a piece's own page was read, it must
  show the same part number; its price and photo are taken
  from that page;
- brand and fit: a piece of another brand, or a different
  drive size than the set's, is dropped (a 1/2" impact
  wrench cannot belong to a 3/8" socket set);
- duplicates merge by part number;
- photo provenance: a piece's photo counts only when it
  came from the piece's own page or the contents section;
- price sanity is a warning only, never a verdict.

The verdict is verified / partial / conflict, with the exact
gaps named ("4 deep sockets: 13, 15, 17, 18") so the agent
can work on precisely what's missing.
"""

from __future__ import annotations

import re

from app.modules.catalog.normalize import norm_model

_SIZE_IN_MODEL_RE = re.compile(r"^[A-Za-z]+?(\d+(?:\.\d+)?)")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_DRIVE_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*(?:in\b|\")")


def _piece_size(piece: dict) -> float | None:
    """The size a piece's part number or name states
    (BUP17M6V -> 17, '19MM DEEP SOCKET' -> 19)."""
    model = str(piece.get("model") or "")
    match = _SIZE_IN_MODEL_RE.match(model)
    if match:
        return float(match.group(1))
    name = str(piece.get("name") or "")
    match = _NUMBER_RE.search(name)
    return float(match.group(0)) if match else None


def _drive_of(text: str) -> str | None:
    match = _DRIVE_RE.search(text or "")
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def _group_keyword(group: dict) -> str:
    """The distinguishing word of a makeup group ('deep',
    'extension', 'adapter', 'standard') — what told this
    group apart from the others in the description."""
    text = f"{group.get('type') or ''}".lower()
    for word in ("deep", "extension", "adapter", "standard", "shallow"):
        if word in text:
            return word
    words = [
        w for w in re.findall(r"[a-z]+", text) if w not in ("socket", "sockets", "piece", "pieces", "set")
    ]
    return words[0] if words else ""


def _matches_group(piece: dict, group: dict, keyword: str) -> bool:
    name = f"{piece.get('name') or ''}".lower()
    if keyword == "standard":
        if any(w in name for w in ("deep", "extension", "adapter")):
            return False
    elif keyword and keyword not in name:
        return False
    size_from = group.get("size_from")
    size_to = group.get("size_to")
    if size_from is not None and size_to is not None:
        size = _piece_size(piece)
        if size is None or not (float(size_from) <= size <= float(size_to)):
            return False
    return True


def judge(
    proposal: dict,
    *,
    cross_sell_models: set[str] | None = None,
    contents_models: set[str] | None = None,
    contents_images: set[str] | None = None,
    piece_pages: dict[str, dict] | None = None,
    evidence_stated_count: int | None = None,
) -> dict:
    """Judge one proposal. `piece_pages` maps a normalized
    part number to what its own page showed: {found, msrp,
    image_url, brand, drive}. `evidence_stated_count` is the
    piece count the run's own opened pages stated (titles and
    headings the system read, never the agent's claim): when
    the evidence states a count, the proposal is judged as a
    set of at least that many pieces whatever it claims —
    a set may not verify as a bare product by omitting its
    count (live failure, 2026-11-20: a 10-piece set verified
    with zero pieces). Returns the verdict dict."""
    cross_sell = {norm_model(m) for m in (cross_sell_models or set())}
    contents = {norm_model(m) for m in (contents_models or set())}
    contents_images = contents_images or set()
    piece_pages = piece_pages or {}

    product = proposal.get("product") or {}
    stated = proposal.get("stated_piece_count")
    if evidence_stated_count:
        stated = max(int(stated or 0), int(evidence_stated_count))
    is_set = bool(proposal.get("is_set")) or (stated or 0) >= 2
    set_drive = _drive_of(
        f"{product.get('size') or ''} {product.get('name') or ''}"
    )
    set_brand = str(product.get("brand") or "").strip().lower()

    dropped: list[dict] = []
    unconfirmed: list[dict] = []
    warnings: list[str] = []

    # Duplicates merge first (quantities kept).
    merged: dict[str, dict] = {}
    for raw in proposal.get("pieces") or []:
        key = norm_model(str(raw.get("model") or ""))
        if not key:
            dropped.append({"model": raw.get("model"), "reason": "no part number"})
            continue
        if key in merged:
            merged[key]["qty"] = (merged[key].get("qty") or 1) + (
                raw.get("qty") or 1
            )
            continue
        merged[key] = dict(raw)

    confirmed: list[dict] = []
    for key, piece in merged.items():
        model = piece.get("model")
        # No cross-sell: in a similar/related rail and NOT in
        # the contents section -> out, whatever it costs.
        if key in cross_sell and key not in contents:
            dropped.append({"model": model, "reason": "cross-sell section"})
            continue
        page = piece_pages.get(key)
        # Brand and fit, where the piece's own page told us.
        if page is not None:
            page_brand = str(page.get("brand") or "").strip().lower()
            if page_brand and set_brand and page_brand != set_brand:
                dropped.append({"model": model, "reason": "different brand"})
                continue
            page_drive = page.get("drive") or _drive_of(
                f"{page.get('name') or ''} {page.get('size') or ''}"
            )
            if page_drive and set_drive and page_drive != set_drive:
                dropped.append(
                    {"model": model, "reason": "does not fit the set (drive)"}
                )
                continue
            if not page.get("found"):
                unconfirmed.append(
                    {"model": model, "reason": "own page did not confirm it"}
                )
                continue
            # The piece's own page is the authority for its
            # price and photo.
            if page.get("msrp") is not None:
                piece["msrp"] = page["msrp"]
            if page.get("image_url"):
                piece["image_url"] = page["image_url"]
        # Photo provenance: a photo from anywhere but the
        # piece's own page or the contents section doesn't
        # count — the piece stays, the photo goes.
        image = piece.get("image_url")
        if image:
            page_image = (page or {}).get("image_url")
            if image != page_image and image not in contents_images:
                piece["image_url"] = None
                warnings.append(f"{model}: photo dropped (unproven source)")
        # Evidence: a piece with nothing behind it is a guess.
        if not piece.get("evidence"):
            unconfirmed.append({"model": model, "reason": "no evidence"})
            continue
        confirmed.append(piece)

    gaps: list[str] = []
    status = "verified"

    # Makeup — only when the groups add up to the stated
    # count (the review guard: an AI extraction that doesn't
    # sum to the stated count is ignored, never enforced).
    makeup = proposal.get("makeup") or []
    makeup_applies = False
    if makeup and stated:
        total = sum(int(g.get("qty") or 0) for g in makeup)
        if total == stated:
            makeup_applies = True
        else:
            warnings.append(
                f"makeup ignored: groups sum to {total}, stated count is {stated}"
            )
    if makeup_applies:
        used: set[str] = set()
        for group in makeup:
            keyword = _group_keyword(group)
            need = int(group.get("qty") or 0)
            filled = []
            for piece in confirmed:
                key = norm_model(str(piece.get("model") or ""))
                if key in used:
                    continue
                if _matches_group(piece, group, keyword):
                    filled.append(piece)
                    used.add(key)
                    if len(filled) >= need:
                        break
            if len(filled) < need:
                missing_sizes = []
                if group.get("size_from") is not None and group.get(
                    "size_to"
                ) is not None:
                    have = {
                        _piece_size(p)
                        for p in filled
                    }
                    step = 1.0
                    size = float(group["size_from"])
                    while size <= float(group["size_to"]):
                        if size not in have:
                            missing_sizes.append(
                                str(int(size)) if size == int(size) else str(size)
                            )
                        size += step
                label = group.get("type") or keyword or "pieces"
                gap = f"{need - len(filled)} x {label}"
                if missing_sizes:
                    gap += f" (sizes: {', '.join(missing_sizes)})"
                gaps.append(gap)

    # Count — pure code, always applies to a set.
    if is_set:
        if stated is None:
            status = "partial"
            gaps.append("the set's stated piece count was never found")
        elif len(confirmed) != stated:
            status = "partial"
            gaps.append(
                f"{len(confirmed)} of {stated} pieces confirmed"
            )
    if gaps:
        status = "partial"
    if unconfirmed and status == "verified":
        status = "partial"
        gaps.append(f"{len(unconfirmed)} piece(s) unconfirmed")

    # Price sanity — a warning only, never a verdict.
    set_price = product.get("msrp")
    if set_price:
        total = sum(
            float(p.get("msrp") or 0) * (p.get("qty") or 1) for p in confirmed
        )
        if confirmed and total < 0.8 * float(set_price):
            warnings.append(
                f"piece prices sum to {total:.2f}, under 80% of the set price"
            )

    if proposal.get("source_conflict"):
        status = "conflict"

    return {
        "status": status,
        "confirmed": confirmed,
        "dropped": dropped,
        "unconfirmed": unconfirmed,
        "gaps": gaps,
        "warnings": warnings,
        "makeup_applied": makeup_applies,
    }
