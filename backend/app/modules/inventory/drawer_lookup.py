"""AI toolbox drawer lookup (owner spec 2026-10-25, reworked
the same day after the Lookup Truth Audit).

In the add-location flow at tier 2 the user keeps their OWN
name for the location ("Toolbox") and separately enters the
toolbox's make + model for the lookup ("Snap-on KRL1033") — or
pastes the product page link. This module answers with the
model's drawer CONFIGURATIONS; nothing is created here, and the
user picks their configuration and edits the drawer names
before anything exists (creation rides the existing
location-tree machinery).

WHERE AN ANSWER MAY COME FROM, in order:
  1. GROUNDED — a real product page (found through the AI
     provider's web search the manual finder uses, or the
     pasted link) states the configurations. Counts are
     accepted ONLY when
     the page itself ties the number to drawers (the validator
     checks the page text), and multiple genuine configurations
     come back as choices — the owner's "does yours have 10
     drawers or 19 drawers?" case. The answer names its page.
  2. AI RECALL — the fallback the original autofill shipped:
     the drawer action's own model (operator setting, temp 0)
     answers from memory. It is returned as ONE configuration,
     flagged grounded=false so the UI labels it UNVERIFIED in
     plain words — the audit proved recall contradicts itself
     across phrasings (13 vs 11 for the same box), so a menu of
     recall guesses presented as fact is the one forbidden
     outcome. Recall keeps its strict validator: well-formed,
     self-certain, with a named source, or it's NOT FOUND.

Charging mirrors the catalog lookup's rule: the wallet is
charged at the operator's ai.drawer_lookup_price ONLY when the
lookup produced a usable (validated, found) answer — never
while the seam is dark, never on a provider failure, never on
a not-found. A pasted link that can't be read answers
found=false with link_error=true (no charge) so the UI can say
"couldn't read that page" instead of guessing. Raises
ai_service errors so the route maps them the same way the
catalog routes do (503 ai_not_configured / 502 ai_provider_error
/ 402 insufficient_credits).
"""

import re
import uuid

from sqlalchemy.orm import Session

from app.modules.billing import ai_service
from app.modules.catalog import grounded

# A real rolling cabinet tops out far below this; anything past
# it is a hallucinated number, not a spec.
_MAX_DRAWERS = 100
_MAX_SECTIONS = 5
_MAX_CONFIGURATIONS = 6

_AI_SYSTEM = (
    "You identify tool storage products — rolling tool cabinets, "
    "toolboxes, and chests — from their make and model. Reply "
    "with a single JSON object only."
)

_CONFIG_AI_SYSTEM = (
    "You read tool storage product pages and extract the drawer "
    "configurations they state. Reply with a single JSON object "
    "only."
)


def _prompt(query: str) -> str:
    return (
        "A mechanic is setting up a storage location for a "
        f'toolbox identified as "{query}" (make and model).\n\n'
        "From the manufacturer's published specifications for "
        "that EXACT make and model, how many DRAWERS does it "
        "have?\n\n"
        "Reply with a JSON object of exactly this shape:\n"
        '{"found": true or false, '
        '"drawer_count": <integer or null>, '
        '"source": "<where the count comes from>", '
        '"extra_sections": ["<section name>", ...]}\n\n'
        "Rules:\n"
        "- found=true ONLY when you are confident of the exact "
        "factory drawer count for that exact model from the "
        "manufacturer's own published specifications. If you "
        "are unsure, the count varies by configuration, or the "
        "product is not a real toolbox model you recognize, "
        'answer found=false with drawer_count null, source "", '
        "and extra_sections empty.\n"
        "- Never guess, estimate, or average across a product "
        "line. A wrong count is worse than no answer.\n"
        "- source must name where the count comes from (for "
        'example "Snap-on official product page — KRL1033"), in '
        "under 120 characters.\n"
        "- extra_sections: only non-drawer storage sections "
        "the manufacturer's specifications clearly list as "
        "separate sections (for example a top till). Names "
        "only, at most 5. Leave the list empty when the "
        "specifications don't clearly name any.\n"
    )


def _clean_sections(raw: object) -> list[str]:
    """Extra sections survive only as short, distinct names."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        name = item.strip()[:80]
        if name and name not in out:
            out.append(name)
        if len(out) >= _MAX_SECTIONS:
            break
    return out


def _as_count(raw: object) -> int | None:
    """A drawer count is a plain integer (JSON integral floats
    like 13.0 count; strings, booleans, and fractions don't)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    return None


# -- grounded configurations ----------------------------------------------------


def _deterministic_configurations(page: dict) -> list[dict]:
    """Drawer counts the page states in the product's own name
    or title ("72 in. 20 Drawer Roller Cabinet") — page facts
    needing no AI at all."""
    texts = [page.get("title", "")]
    texts += [
        str(candidate.get("name", "")) for candidate in page.get("candidates", [])
    ]
    counts: list[int] = []
    for text in texts:
        for match in re.finditer(r"(\d{1,3})\s*[- ]?drawers?\b", text, re.I):
            count = int(match.group(1))
            if 1 <= count <= _MAX_DRAWERS and count not in counts:
                counts.append(count)
    return [
        {"drawer_count": count, "extra_sections": []} for count in counts
    ]


def _ai_configurations(db: Session, page: dict, model: str) -> list[dict]:
    """The AI reads the fetched page for the model's drawer
    configurations. A claimed count survives ONLY when the
    page itself ties that number to drawers (grounded's
    count_supported); claimed sections must appear on the
    page too. Raises ai_service errors — the caller treats a
    dark/failing seam as "no AI pass", never a failed page."""
    prompt = (
        "Below is the text of ONE product page for a toolbox"
        + (f' (the user is setting up "{model}")' if model else "")
        + ". List the distinct factory DRAWER CONFIGURATIONS "
        "this exact model is sold in, using ONLY facts the page "
        "states — never outside knowledge. Reply with a JSON "
        "object of exactly this shape:\n"
        '{"configurations": [{"drawer_count": <integer>, '
        '"extra_sections": ["<section name>", ...]}]}\n\n'
        "Rules:\n"
        "- One entry per distinct drawer count the PAGE states "
        "for this model. If the page states a single count, "
        "list exactly one entry.\n"
        "- extra_sections: non-drawer storage sections the page "
        "names for that configuration (for example a top till). "
        "Names only, at most 5; empty when the page names none.\n"
        "- If the page does not state any drawer count for this "
        'model, answer {"configurations": []}.\n\n'
        f"Page title: {page['title']}\n\nPage text:\n"
        + grounded.page_excerpt(page, model)
    )
    data = ai_service.complete_json(
        db,
        prompt,
        system=_CONFIG_AI_SYSTEM,
        model_name=ai_service.model_for(db, "drawer_lookup"),
        temperature=0.0,
    )
    raw = data.get("configurations")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen: set[int] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        count = _as_count(entry.get("drawer_count"))
        if count is None or not (1 <= count <= _MAX_DRAWERS):
            continue
        if count in seen or not grounded.count_supported(count, page):
            continue
        seen.add(count)
        sections = [
            name
            for name in _clean_sections(entry.get("extra_sections"))
            if grounded.value_supported(name, page)
        ]
        out.append({"drawer_count": count, "extra_sections": sections})
        if len(out) >= _MAX_CONFIGURATIONS:
            break
    return out


def _grounded_configurations(db: Session, page: dict, model: str) -> list[dict]:
    """Every configuration one fetched page supports:
    deterministic name/title counts unioned with the AI-read
    ones (the AI's entry wins a shared count — it read the
    whole page, sections included)."""
    merged: dict[int, dict] = {}
    for config in _deterministic_configurations(page):
        merged[config["drawer_count"]] = config
    if ai_service.ai_configured(db):
        try:
            ai_configs = _ai_configurations(db, page, model)
        except (ai_service.AiNotConfigured, ai_service.AiProviderError):
            ai_configs = []
        for config in ai_configs:
            merged[config["drawer_count"]] = config
    return [merged[count] for count in sorted(merged)]


def _grounded_answer(db: Session, user_id: uuid.UUID, page: dict, model: str) -> dict | None:
    """A validated grounded answer off one page, or None when
    the page supports no configuration. Charging happens here,
    once, only for a validated find."""
    ai_service.begin_usage_capture()
    configurations = _grounded_configurations(db, page, model)
    if not configurations:
        return None
    charged = ai_service.charge_for(
        db, user_id, "drawer_lookup", subject=model
    )
    single = configurations[0] if len(configurations) == 1 else None
    return {
        "found": True,
        "grounded": True,
        "drawer_count": single["drawer_count"] if single else None,
        "source": page["site_name"],
        "source_url": page["url"],
        "configurations": configurations,
        "extra_sections": single["extra_sections"] if single else [],
        "link_error": False,
        "charged": charged,
    }


def _not_found(*, link_error: bool = False) -> dict:
    return {
        "found": False,
        "grounded": False,
        "drawer_count": None,
        "source": None,
        "source_url": None,
        "configurations": [],
        "extra_sections": [],
        "link_error": link_error,
        "charged": 0,
    }


def _recall(db: Session, user_id: uuid.UUID, model: str) -> dict:
    """The AI-recall fallback: one configuration at most,
    flagged unverified (grounded=false). The strict shipped
    validator stands — malformed, sourceless, out-of-range, or
    self-declared not-found is a plain miss and charges
    nothing. Raises AiNotConfigured while the seam is dark."""
    ai_service.begin_usage_capture()
    data = ai_service.complete_json(
        db,
        _prompt(model),
        system=_AI_SYSTEM,
        model_name=ai_service.model_for(db, "drawer_lookup"),
        # Factual recall stays deterministic: at the provider
        # default the same model answered the same box with 13,
        # 15, and 17 drawers across calls; pinned to 0 it gives
        # its best single answer every time (verified live,
        # 2026-10-25). The confirm step remains the human check.
        temperature=0.0,
    )
    count = _as_count(data.get("drawer_count"))
    source = data.get("source")
    source = source.strip()[:200] if isinstance(source, str) else ""
    found = (
        data.get("found") is True
        and count is not None
        and 1 <= count <= _MAX_DRAWERS
        and bool(source)
    )
    if not found:
        return _not_found()
    sections = _clean_sections(data.get("extra_sections"))
    charged = ai_service.charge_for(
        db, user_id, "drawer_lookup", subject=model
    )
    return {
        "found": True,
        "grounded": False,
        "drawer_count": count,
        "source": source,
        "source_url": None,
        "configurations": [{"drawer_count": count, "extra_sections": sections}],
        "extra_sections": sections,
        "link_error": False,
        "charged": charged,
    }


def lookup_drawers(
    db: Session, user_id: uuid.UUID, model: str, link: str = ""
) -> dict:
    """Answer one drawer lookup for a toolbox make + model.

    Returns {found, grounded, drawer_count, source, source_url,
    configurations, extra_sections, link_error, charged}.
    Raises ai_service.AiNotConfigured while the seam is dark
    (and no grounded page answered), ai_service.AiProviderError
    on a failed recall call, and wallet.InsufficientCredits
    when a found answer can't be paid for."""
    model = (model or "").strip()
    link = (link or "").strip()

    if link:
        try:
            page = grounded.fetch_product_page(link)
        except grounded.PageFetchError:
            return _not_found(link_error=True)
        answer = _grounded_answer(db, user_id, page, model)
        if answer is not None:
            return answer
        # The page read but states no drawer count. Fall through
        # to recall when there is a model to ask about; the UI
        # labels that answer unverified, as always.
        if not model:
            return _not_found()
        return _recall(db, user_id, model)

    if model and grounded.search_configured(db):
        query = f"{model} toolbox"
        for result in grounded.search_pages(db, query)[:3]:
            try:
                page = grounded.fetch_product_page(result["url"])
            except grounded.PageFetchError:
                continue
            answer = _grounded_answer(db, user_id, page, model)
            if answer is not None:
                return answer

    if not model:
        return _not_found()
    return _recall(db, user_id, model)
