"""The layered lookup chain (wave 4) — ONE service behind Quick
Add: given a brand+model and/or a UPC, propose the spec fields a
new item probably wants, every value labeled with its source.

PROVIDER ORDER (documented contract — first confident hit wins
per field; later layers only supplement fields still missing):

  a) COMMUNITY CATALOG (catalog.service) — values >= 2 distinct
     contributing users agree on. Always available, costs
     nothing, and is the only layer whose numbers are the
     community's own.
  b) UPC / BARCODE DATABASE — only when a UPC was supplied AND
     the operator configured the layer (Admin -> Settings:
     lookup.upc_provider + lookup.upc_api_key_ref). Dark layers
     are skipped silently. Implemented against UPCitemdb's
     lookup response shape.
  c) GROUNDED WEB (catalog.grounded) — reads the facts off a
     real product page: the AI provider's web search finds the
     page (the manual finder's layer, same AI seam) or the user
     pastes the page link directly. Structured page data first,
     then the AI READS the page text for gaps — every AI-read
     value must be supported by the page or it is dropped. The
     result names its source page and may carry the page's real
     product photo.
  d) AI ASSIST (billing.ai_service) — only when the AI seam is
     configured; proposes from the brand/model/UPC context.
     HARDENED (2026-10-25, Lookup Truth Audit): pinned to
     temperature 0 (a retry is no longer a dice re-roll), and
     any value that merely ECHOES what the user typed is
     stripped — an echo is not found content. Charged at the
     operator's ai.lookup_price ONLY when an AI call actually
     runs and contributes (never when a layer is dark, never
     when it errors, never for an echo-only reply). A provider
     failure skips the layer — the chain still answers.
  e) Nothing found -> empty fields; the UI falls back to manual
     entry. The chain never invents a value to fill a gap.

A result with real details but NO verified name is PARTIAL
(`partial: true`) — the surfaces say so plainly instead of
dressing it up as a full hit with a title composed from the
user's own typing.

Every returned field is {value, source, detail}:
  source "community" — detail "N owners agree"
  source "barcode"   — detail the provider's name
  source "web"       — detail the page/site the fact was read from
  source "ai"        — detail "AI suggestion — check it"
"""

import uuid

import httpx
from sqlalchemy.orm import Session

from app.core.config import env_value
from app.modules.billing import ai_service
from app.modules.catalog import grounded, lookup_config, service
from app.modules.catalog.normalize import canonical_brand, norm_text, resolve_brand

_FIELDS = ("name", "brand", "model", "category", "size", "msrp", "description")

_HTTP_TIMEOUT_SECONDS = 15.0


# -- echo hardening -------------------------------------------------------------


def _input_norms(*values: str) -> set[str]:
    """The normalized forms of everything the user typed — the
    yardstick an AI value is measured against for echo-ness."""
    norms = {norm_text(value) for value in values if value}
    combined = norm_text(" ".join(value for value in values if value))
    if combined:
        norms.add(combined)
    norms.discard("")
    return norms


def _is_echo(value: object, input_norms: set[str]) -> bool:
    """True when an AI value merely hands the user's own typing
    back: its normalized form IS one of the inputs, or (for a
    proposed name) it is built from nothing but input tokens —
    "Matco SPRB4A" proposed as the NAME of a Matco SPRB4A lookup
    is the user's input wearing a name tag, not a find."""
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = norm_text(value)
    if not normalized:
        return False
    if normalized in input_norms:
        return True
    input_tokens: set[str] = set()
    for norm in input_norms:
        input_tokens.update(norm.split())
    tokens = normalized.split()
    return bool(tokens) and all(token in input_tokens for token in tokens)


def _strip_echoes(values: dict, input_norms: set[str]) -> dict:
    return {
        key: value
        for key, value in values.items()
        if not _is_echo(value, input_norms)
    }


# -- UPC layer ---------------------------------------------------------------


def upc_configured(db: Session) -> bool:
    from app.modules.billing import entitlements

    provider_name = (
        entitlements.get_setting(db, lookup_config.UPC_PROVIDER_KEY, "") or ""
    ).strip()
    ref = (
        entitlements.get_setting(db, lookup_config.UPC_API_KEY_REF_KEY, "") or ""
    ).strip()
    return provider_name == "upcitemdb" and bool(ref) and bool(env_value(ref))


def _upc_transport(url: str, headers: dict, params: dict) -> dict:
    """One GET against the barcode database (stubbed in tests)."""
    try:
        response = httpx.get(
            url, headers=headers, params=params, timeout=_HTTP_TIMEOUT_SECONDS
        )
    except httpx.HTTPError:
        return {}
    if response.status_code != 200:
        return {}
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def upc_lookup(db: Session, upc: str) -> dict:
    """Field proposals from the barcode database for one UPC
    ({} when the layer is dark or the UPC is unknown)."""
    from app.modules.billing import entitlements

    if not upc_configured(db):
        return {}
    ref = (
        entitlements.get_setting(db, lookup_config.UPC_API_KEY_REF_KEY, "") or ""
    ).strip()
    body = _upc_transport(
        "https://api.upcitemdb.com/prod/v1/lookup",
        {"user_key": env_value(ref)},
        {"upc": upc},
    )
    items = body.get("items") or []
    if not items or not isinstance(items[0], dict):
        return {}
    item = items[0]
    out: dict = {}
    if item.get("title"):
        out["name"] = str(item["title"]).strip()
    if item.get("brand"):
        out["brand"] = str(item["brand"]).strip()
    if item.get("model"):
        out["model"] = str(item["model"]).strip()
    if item.get("category"):
        # UPCitemdb categories arrive as "Hardware > Tools > …"
        # paths; the leaf is the usable category.
        out["category"] = str(item["category"]).split(">")[-1].strip()
    price = item.get("highest_recorded_price") or item.get("lowest_recorded_price")
    if price:
        out["msrp"] = price
    description = item.get("description")
    if isinstance(description, str):
        description = " ".join(description.split())
        if 20 <= len(description) <= 2000:
            out["description"] = description
    return out


# -- AI layer ------------------------------------------------------------------

_AI_SYSTEM = (
    "You identify tools and shop equipment. Reply with a single "
    "JSON object only."
)


def _ai_lookup_fields(db: Session, brand: str, model: str, upc: str) -> dict:
    """The AI layer's raw proposals ({} when it has nothing).
    Raises ai_service errors — the chain decides what they mean.
    Pinned to temperature 0: factual lookup is not a creative
    task, and the audit proved the default sampling makes a
    retry return a different (sometimes invented) product."""
    context = []
    if brand:
        context.append(f"brand: {brand}")
    if model:
        context.append(f"model: {model}")
    if upc:
        context.append(f"UPC barcode: {upc}")
    prompt = (
        "A mechanic is cataloguing an item with "
        + (", ".join(context) if context else "no details")
        + ". Propose the most likely product facts as JSON with "
        'keys among {"name","brand","model","category","size","msrp","description"} '
        "(msrp a number in USD, size a short string like \"1/2 in drive\", "
        "description one or two plain sentences saying what the item is). "
        "Omit any key you are not reasonably confident about."
    )
    data = ai_service.complete_json(db, prompt, system=_AI_SYSTEM, temperature=0.0)
    out = {
        key: data[key]
        for key in _FIELDS
        if key in data and data[key] not in (None, "")
    }
    # A recalled "description" is a sentence or it is nothing —
    # the same length discipline the grounded pipe applies.
    description = out.get("description")
    if description is not None and not (
        isinstance(description, str) and 20 <= len(description.strip()) <= 1000
    ):
        out.pop("description", None)
    return out


# -- the chain -----------------------------------------------------------------


def run_lookup(
    db: Session,
    user_id: uuid.UUID,
    *,
    brand: str = "",
    model: str = "",
    upc: str = "",
    link: str = "",
) -> dict:
    """Run the chain. Returns {fields, sources, ai_charged,
    partial, image_url, source_name, source_url, web_configured,
    link_error} — fields maps field name -> {value, source,
    detail}. A pasted product `link` runs the grounded layer
    against THAT page; when the page can't be read, the chain
    answers link_error and does NOT fall back to an AI guess —
    the user pointed at a specific source."""
    ai_service.begin_usage_capture()
    fields: dict[str, dict] = {}
    sources: list[str] = []

    def fill(
        values: dict,
        source: str,
        detail: str,
        supporters: dict | None = None,
    ) -> bool:
        added = False
        for key in _FIELDS:
            if key in fields or key not in values:
                continue
            value = values[key]
            if value in (None, ""):
                continue
            entry = {"value": value, "source": source, "detail": detail}
            # Community entries also carry the supporter count
            # numerically (the read contract from the catalog
            # spec); the detail string stays the human label.
            if supporters and key in supporters:
                entry["supporters"] = supporters[key]
            fields[key] = entry
            added = True
        if added and source not in sources:
            sources.append(source)
        return added

    # (a) Community catalog — keyed by brand+model. Filled field
    # by field so each carries its OWN supporter count.
    if brand and model:
        suggestions = service.suggestions_for(db, brand, model)
        for field, info in suggestions["fields"].items():
            fill(
                {field: info["value"]},
                "community",
                f"{info['supporters']} owners agree",
                supporters={field: info["supporters"]},
            )

    # (b) Barcode database — keyed by the UPC alone.
    if upc:
        fill(upc_lookup(db, upc), "barcode", "UPCitemdb")

    ai_charged = 0

    def charge_ai_once() -> None:
        nonlocal ai_charged
        if not ai_charged:
            subject = (
                " ".join(part for part in (brand, model) if part)
                or upc
                or link
            )
            ai_charged = ai_service.charge_for(
                db, user_id, "lookup", subject=subject
            )

    # (c) Grounded web — facts read off a real product page.
    image_url = None
    source_name = None
    source_url = None
    link_error = False
    grounded_ran = False

    def fill_grounded(grounded_result: dict) -> None:
        nonlocal source_name, source_url, image_url
        values = dict(grounded_result["fields"])
        if values.get("brand"):
            # The page's brand may be a manufacturer code the
            # miner already expanded (C-08); when the user typed
            # a brand, their typing wins over the code.
            values["brand"] = resolve_brand(str(values["brand"]), brand)
        fill(values, "web", grounded_result["source_name"])
        source_name = grounded_result["source_name"]
        source_url = grounded_result["source_url"]
        image_url = grounded_result["image_url"]
        if grounded_result["ai_used"]:
            charge_ai_once()

    if link:
        grounded_ran = True
        try:
            grounded_result = grounded.grounded_product(
                db, brand=brand, model=model, link=link
            )
        except grounded.PageFetchError:
            grounded_result = None
            link_error = True
        if grounded_result is not None:
            if grounded_result["fields"]:
                fill_grounded(grounded_result)
            else:
                # The page read, but nothing usable came off it —
                # from the user's seat the link didn't work.
                link_error = True
    elif (brand or model) and grounded.search_configured(db):
        grounded_ran = True
        grounded_result = grounded.grounded_product(db, brand=brand, model=model)
        if grounded_result is not None and grounded_result["fields"]:
            fill_grounded(grounded_result)

    # (d) AI assist — only while something worth proposing is
    # still missing AND the seam is lit. Echoes are stripped
    # before anything counts: a reply that only hands the user's
    # typing back is a miss, and charges nothing. Skipped
    # entirely when a pasted link failed — no guessing on top
    # of a source the user chose — AND when the grounded layer
    # answered: once a real page has spoken for this product,
    # memory-based specs are exactly what the grounded pipe
    # exists to replace (the audit's DCF891 came back with a
    # grounded name and a hallucinated 1/4-inch size riding
    # underneath until this rule landed).
    grounded_hit = any(
        entry["source"] == "web" for entry in fields.values()
    )
    missing = [f for f in ("category", "size", "msrp") if f not in fields]
    if (
        missing
        and not link_error
        and not grounded_hit
        and (brand or model or upc)
        and ai_service.ai_configured(db)
    ):
        try:
            ai_values = _ai_lookup_fields(db, brand, model, upc)
        except ai_service.AiProviderError:
            ai_values = {}
        ai_values = _strip_echoes(ai_values, _input_norms(brand, model, upc))
        if ai_values:
            charge_ai_once()
            fill(ai_values, "ai", "AI suggestion — check it")

    # Mismatch honesty (C-08): when the winning page is for a
    # different version than the model the user typed (the
    # DCF891P2 kit for a typed DCF891), the result SAYS SO —
    # model_mismatch + found_model travel with the payload and
    # the card renders them in plain words before the user's
    # explicit "Use this" can prefill anything.
    found_model = (
        str(fields["model"]["value"]) if fields.get("model") else None
    )
    model_mismatch = bool(
        model
        and found_model
        and norm_text(found_model) != norm_text(model)
    )
    return {
        "fields": fields,
        "sources": sources,
        "ai_charged": ai_charged,
        "partial": bool(fields) and "name" not in fields,
        "image_url": image_url,
        "source_name": source_name,
        "source_url": source_url,
        "web_configured": grounded.search_configured(db),
        "link_error": link_error,
        "model_mismatch": model_mismatch,
        "found_model": found_model if model_mismatch else None,
    }


# -- item identification (AI feature, Quick Add) -------------------------------


def identify(db: Session, user_id: uuid.UUID, text: str) -> dict:
    """AI item identification: a free-text description (or a
    listing title) -> proposed {name, brand, model, category}.

    Unlike the chain, this surface is AI-or-nothing, so the dark
    seam surfaces honestly: raises ai_service.AiNotConfigured
    (the route answers 503 ai_not_configured). Hardened like the
    chain (2026-10-25): temperature 0, and a proposed NAME that
    merely restates the input (or the AI's own brand/model) is
    dropped — with no real name the result is partial, never a
    dressed-up success, and an echo-only reply charges nothing."""
    ai_service.begin_usage_capture()
    prompt = (
        "A mechanic describes an item in their toolbox:\n\n"
        f"{text.strip()}\n\n"
        "Identify the item. Reply with a JSON object with keys "
        '{"name","brand","model","category"} — your best proposal '
        "for each; use an empty string for anything the text "
        "doesn't support."
    )
    data = ai_service.complete_json(db, prompt, system=_AI_SYSTEM, temperature=0.0)
    # A name is an echo here only when it restates the WHOLE
    # input (or the reply's own brand/model) verbatim — a real
    # identify name legitimately draws words from a longer
    # description, so the chain's token-subset rule does not
    # apply to this surface.
    text_norm = norm_text(text)
    fields = {}
    for key in ("name", "brand", "model", "category"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if norm_text(value) == text_norm:
            # The whole input restated in one slot is an echo,
            # whichever slot it lands in.
            continue
        if key == "name" and norm_text(value) in {
            text_norm,
            norm_text(str(data.get("model", ""))),
            norm_text(str(data.get("brand", ""))),
        }:
            continue
        if key == "brand":
            value = canonical_brand(value)
        fields[key] = {
            "value": value,
            "source": "ai",
            "detail": "AI suggestion — check it",
        }
    if not fields:
        return {
            "fields": {},
            "sources": [],
            "ai_charged": 0,
            "partial": False,
            "image_url": None,
            "source_name": None,
            "source_url": None,
            "web_configured": grounded.search_configured(db),
            "link_error": False,
        }
    charged = ai_service.charge_for(
        db, user_id, "identify", subject=text.strip()
    )
    return {
        "fields": fields,
        "sources": ["ai"],
        "ai_charged": charged,
        "partial": "name" not in fields,
        "image_url": None,
        "source_name": None,
        "source_url": None,
        "web_configured": grounded.search_configured(db),
        "link_error": False,
    }


# -- photo identification (AI wizard completion, 2026-11-07) -------------------
#
# Ryan's doctrine: every path into entry — type it, look it up,
# PHOTO it. The photo goes through the same AI seam (vision
# rides ai_service.complete_json's image parameter), and the
# answer is only ever a PROPOSAL: the wizard shows it with its
# confidence stated plainly, the user confirms, and the
# identification then feeds the ordinary grounded lookup — so
# the facts that finally fill the form still come from the
# verified product page, never from the photo read itself.
# Metering rides the existing identify price (ai.identify_price,
# default 0 = free) with the same charge-after-success rule: an
# unreadable photo, a provider failure, or an answer with no
# usable fields charges nothing.

_PHOTO_ID_MAX_BYTES = 8 * 1024 * 1024


class PhotoUnreadable(ValueError):
    """The uploaded bytes are not a usable photo (empty, over
    the size cap, or not a JPEG/PNG/WebP at all). The route
    answers 422 {code: photo_unreadable} and the wizard lands
    the user softly back on the typed path."""


def _sniff_photo_mime(data: bytes) -> str | None:
    """The photo's real type from its first bytes — a declared
    mime is never trusted (the same byte-sniff discipline as
    the product-photo download in grounded.fetch_photo)."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def identify_photo(db: Session, user_id: uuid.UUID, image_data: bytes) -> dict:
    """AI identification from ONE photo of the item (or its
    label) -> proposed {name, brand, model, category} plus the
    model's own stated confidence ("high" | "medium" | "low";
    None when the reply carries nothing usable — the UI then
    treats the read as a plain guess). Same result contract as
    identify(); like identify() this surface is AI-or-nothing:
    the dark seam raises AiNotConfigured (503 at the route) and
    a provider failure raises AiProviderError (502)."""
    import base64

    if not image_data:
        raise PhotoUnreadable("That photo came through empty.")
    if len(image_data) > _PHOTO_ID_MAX_BYTES:
        raise PhotoUnreadable("That photo is larger than the 8 MB limit.")
    mime = _sniff_photo_mime(image_data)
    if mime is None:
        raise PhotoUnreadable("That file isn't a photo we can read.")
    prompt = (
        "The photo shows a tool, a battery, or other shop "
        "equipment — or its label. Identify what it is. Read any "
        "brand name and model number printed on the item or "
        "label exactly as written. Reply with a JSON object with "
        'keys {"name","brand","model","category","confidence"} '
        "— your best proposal for each, an empty string for "
        "anything the photo does not support — and confidence: "
        '"high" when the brand and model are clearly readable '
        'in the photo, "medium" when the kind of item is clear '
        'but the exact model is a judgment call, "low" when you '
        "are mostly guessing from the item's shape."
    )
    ai_service.begin_usage_capture()
    data = ai_service.complete_json(
        db,
        prompt,
        system=_AI_SYSTEM,
        temperature=0.0,
        image=(mime, base64.b64encode(image_data).decode("ascii")),
    )
    fields = {}
    for key in ("name", "brand", "model", "category"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if key == "name" and norm_text(value) in {
            norm_text(str(data.get("model", ""))),
            norm_text(str(data.get("brand", ""))),
        }:
            # A "name" that merely restates the reply's own
            # brand or model is not a name (identify()'s rule).
            continue
        if key == "brand":
            value = canonical_brand(value)
        fields[key] = {
            "value": value,
            "source": "ai",
            "detail": "AI suggestion — check it",
        }
    confidence = data.get("confidence")
    confidence = (
        confidence.strip().lower()
        if isinstance(confidence, str)
        and confidence.strip().lower() in ("high", "medium", "low")
        else None
    )
    if not fields:
        return {
            "fields": {},
            "sources": [],
            "ai_charged": 0,
            "partial": False,
            "image_url": None,
            "source_name": None,
            "source_url": None,
            "web_configured": grounded.search_configured(db),
            "link_error": False,
            "confidence": confidence,
        }
    charged = ai_service.charge_for(
        db,
        user_id,
        "identify",
        subject=(
            "Photo: "
            + " ".join(
                fields[key]["value"]
                for key in ("brand", "model", "name")
                if key in fields
            )
        ).strip(),
    )
    return {
        "fields": fields,
        "sources": ["ai"],
        "ai_charged": charged,
        "partial": "name" not in fields,
        "image_url": None,
        "source_name": None,
        "source_url": None,
        "web_configured": grounded.search_configured(db),
        "link_error": False,
        "confidence": confidence,
    }
