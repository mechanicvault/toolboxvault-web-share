"""The AI service seam (wave 4, 2026-10-20) — the ONE door every
AI feature walks through (spec: files/ai-token-system.md).

Configuration is operator data, not code (Admin -> Settings):
  ai.provider     — "openai" | "anthropic" ("" = not configured)
  ai.model        — the provider's model name
  ai.api_key_ref  — the NAME of the environment variable holding
                    the key (the key itself never enters the DB)

Until all three are set (and the named env var exists), the seam
is DARK: `ai_configured` is False, every consumer answers
503 {code: ai_not_configured}, and the UI hides its AI surfaces.
Deterministic features (community catalog, duplicate detection,
smart search) never touch this module's client at all.

Per-action credit prices are operator settings too
(ai.<action>_price, whole credits, default 0 = free): a price is
charged through the wallet ONLY when the AI call actually runs —
`charge_for` is called by the consumer after a successful call,
never before, and never on a failure path.

The provider transport is the module-level `_transport` so tests
stub exactly one function; the request/response shapes per
provider live in `_complete_openai` / `_complete_anthropic`.

VISION (AI wizard completion, 2026-11-07): `complete` /
`complete_json` accept an optional `image=(mime, base64_data)`
— one photo rides the SAME seam (OpenAI image content parts;
Anthropic base64 image blocks). Both adapters carry it
natively, so no consumer needs a second door and the metering /
dark-seam discipline is unchanged. A caller that passes no
image gets the exact text-only request shape it always got.
"""

import contextvars
import json
import uuid
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from sqlalchemy.orm import Session

from app.core.config import env_value
from app.modules.billing import entitlements, wallet
from app.modules.billing import models as billing_models

PROVIDER_KEY = "ai.provider"
MODEL_KEY = "ai.model"
API_KEY_REF_KEY = "ai.api_key_ref"

# Per-action credit price settings (whole credits; 0 = free).
PRICE_KEYS = {
    "lookup": "ai.lookup_price",
    "identify": "ai.identify_price",
    "manual_lookup": "ai.manual_lookup_price",
    "report_summary": "ai.report_summary_price",
    "drawer_lookup": "ai.drawer_lookup_price",
}

# Per-action MODEL overrides (operator settings; blank = the
# site model above). Actions differ in what they need from a
# model the same way they differ in price: the drawer lookup
# is a factual-recall action where the site-default mini model
# either declines or misremembers model-specific specs, so the
# operator can point THIS action at a stronger model without
# re-pricing or re-grading every other AI feature.
MODEL_KEYS = {
    "drawer_lookup": "ai.drawer_lookup_model",
}

SUPPORTED_PROVIDERS = ("openai", "anthropic")

_HTTP_TIMEOUT_SECONDS = 30.0
# A search call reads the live web before it answers; it gets a
# longer leash than a plain completion.
_SEARCH_TIMEOUT_SECONDS = 90.0


class AiNotConfigured(RuntimeError):
    """The operator hasn't configured a provider yet. Consumers
    turn this into 503 {code: ai_not_configured}."""


class AiProviderError(RuntimeError):
    """The provider was configured but the call failed (network,
    status, or an unparsable reply)."""


def provider(db: Session) -> str:
    return (entitlements.get_setting(db, PROVIDER_KEY, "") or "").strip()


def model(db: Session) -> str:
    return (entitlements.get_setting(db, MODEL_KEY, "") or "").strip()


def api_key(db: Session) -> str:
    ref = (entitlements.get_setting(db, API_KEY_REF_KEY, "") or "").strip()
    return env_value(ref) if ref else ""


def ai_configured(db: Session) -> bool:
    """True only when a supported provider + model + resolvable
    key are ALL present. One missing leg = dark."""
    return (
        provider(db) in SUPPORTED_PROVIDERS
        and bool(model(db))
        and bool(api_key(db))
    )


def status(db: Session) -> dict:
    """The UI-safe posture: whether AI surfaces may render, and
    which provider/model would serve them. Never any key material."""
    return {
        "configured": ai_configured(db),
        "provider": provider(db),
        "model": model(db),
    }


def model_for(db: Session, action: str) -> str:
    """The model that serves one action: its operator-set
    override when one exists, else the site model. Unknown
    actions have no override and always ride the site model."""
    key = MODEL_KEYS.get(action)
    if key is not None:
        override = (entitlements.get_setting(db, key, "") or "").strip()
        if override:
            return override
    return model(db)


def price_for(db: Session, action: str) -> int:
    """The credit price of one AI action (0 = free). Unknown
    actions are free — a price can only exist for a named action."""
    key = PRICE_KEYS.get(action)
    if key is None:
        return 0
    raw = entitlements.get_setting(db, key, 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


# -- usage metering (admin polish lane, owner 2026-11-07) -------------------
#
# The wallet ledger alone could never answer "when did this
# account use AI, for what, and how many tokens did it take":
# it records spends only (at the default price of 0 there IS no
# spend), and the transports used to discard the providers'
# usage counts. So: while a consumer flow runs, the transports
# note every provider call's token counts into a per-flow
# capture; `charge_for` — the one door every metered action
# already walks through after a successful call — drains the
# capture into one AiUsage row, free actions included. A flow
# opens its capture with begin_usage_capture(); a charge taken
# with no capture open still records (calls/tokens read 0 —
# the spend happened; its token counts were never captured).

_usage_capture: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "ai_usage_capture", default=None
)


def begin_usage_capture() -> None:
    """Open a fresh per-flow capture. Consumers call this at
    the start of one metered action's work; the transports feed
    it and the action's charge_for drains it."""
    _usage_capture.set(
        {"calls": 0, "tokens_in": 0, "tokens_out": 0, "provider": ""}
    )


def _note_usage(provider_name: str, body: object) -> None:
    """One provider round-trip's token counts, noted by the
    transports. Both providers name the fields their own way
    (OpenAI chat: prompt/completion tokens; everything else:
    input/output tokens). A reply without a usage block still
    counts as a call — its tokens are honestly unknown (0)."""
    acc = _usage_capture.get()
    if acc is None:
        return
    acc["calls"] += 1
    acc["provider"] = provider_name
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return
    acc["tokens_in"] += int(
        usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    )
    acc["tokens_out"] += int(
        usage.get("completion_tokens") or usage.get("output_tokens") or 0
    )


def _record_usage(
    db: Session,
    user_id: uuid.UUID,
    action: str,
    subject: str,
    charged: int,
) -> None:
    """Drain the capture into one AiUsage row. A row is written
    when the action actually consumed something — a provider
    call was captured, or a charge was taken. A free action
    that resolved deterministically (no provider call, no
    charge) used no AI and records nothing. Recording is
    bookkeeping next to the wallet's money truth: a failure
    here rolls back its own write and never fails the action
    the user already got."""
    acc = _usage_capture.get()
    calls = int(acc["calls"]) if acc else 0
    if calls <= 0 and charged <= 0:
        return
    row = billing_models.AiUsage(
        user_id=user_id,
        action=action,
        subject=(subject or "").strip()[:300],
        provider=(acc["provider"] if acc else "") or provider(db),
        model=model_for(db, action),
        calls=calls,
        tokens_in=int(acc["tokens_in"]) if acc else 0,
        tokens_out=int(acc["tokens_out"]) if acc else 0,
        credits_charged=charged,
    )
    db.add(row)
    try:
        db.commit()
    except Exception:  # noqa: BLE001 — bookkeeping, see docstring
        db.rollback()
        return
    if acc is not None:
        acc.update(calls=0, tokens_in=0, tokens_out=0, provider="")


def charge_for(
    db: Session, user_id: uuid.UUID, action: str, subject: str = ""
) -> int:
    """Charge the action's price AFTER a successful AI call.
    Returns the credits charged (0 when the action is free).
    Raises wallet.InsufficientCredits when the wallet can't pay —
    consumers surface that as their own refusal (and nothing is
    recorded — the action is refused, not consumed).

    `subject` is the call's context for the usage record (what
    the lookup/manual/identify was FOR) — consumers pass it;
    the wallet ledger's own `ref` stays the action name, as
    always."""
    price = price_for(db, action)
    charged = 0
    if price > 0:
        wallet.spend(
            db, user_id, amount=price, reason=f"ai_{action}", ref=action
        )
        charged = price
    _record_usage(db, user_id, action, subject, charged)
    return charged


# -- provider transport (stubbed in tests) -----------------------------------


def _transport(
    url: str, headers: dict, payload: dict, timeout: float = _HTTP_TIMEOUT_SECONDS
) -> dict:
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise AiProviderError(f"AI provider request failed: {exc}") from exc
    if response.status_code != 200:
        raise AiProviderError(
            f"AI provider returned HTTP {response.status_code}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise AiProviderError("AI provider returned non-JSON") from exc
    if not isinstance(body, dict):
        raise AiProviderError("AI provider returned an unexpected payload")
    return body


def _complete_openai(
    key: str,
    model_name: str,
    system: str,
    prompt: str,
    temperature: float | None = None,
    image: tuple[str, str] | None = None,
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    if image is None:
        messages.append({"role": "user", "content": prompt})
    else:
        mime, data = image
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"},
                    },
                ],
            }
        )
    payload: dict = {"model": model_name, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature
    body = _transport(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {key}"},
        payload,
    )
    _note_usage("openai", body)
    try:
        return str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise AiProviderError("AI provider reply had no message content") from exc


def _complete_anthropic(
    key: str,
    model_name: str,
    system: str,
    prompt: str,
    temperature: float | None = None,
    image: tuple[str, str] | None = None,
) -> str:
    if image is None:
        content: object = prompt
    else:
        mime, data = image
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": data},
            },
        ]
    payload: dict = {
        "model": model_name,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": content}],
    }
    if system:
        payload["system"] = system
    if temperature is not None:
        payload["temperature"] = temperature
    body = _transport(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
        payload,
    )
    _note_usage("anthropic", body)
    try:
        # The reply's text block (vision replies interleave the
        # same text blocks; take the first one that carries text
        # rather than assuming position 0 forever).
        for block in body["content"]:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                return block["text"]
        raise KeyError("text")
    except (KeyError, IndexError, TypeError) as exc:
        raise AiProviderError("AI provider reply had no text content") from exc


def complete(
    db: Session,
    prompt: str,
    *,
    system: str = "",
    model_name: str | None = None,
    temperature: float | None = None,
    image: tuple[str, str] | None = None,
) -> str:
    """One completion through the configured provider. Raises
    AiNotConfigured while the seam is dark. `model_name` is the
    caller's per-action model (see model_for); None rides the
    site model, as every consumer always has. `temperature`
    likewise passes through only when a caller sets it — a
    factual-recall action pins 0 so the same question gets the
    same answer every time. `image` is an optional (mime,
    base64_data) photo the provider reads alongside the prompt
    (vision); both providers carry it in their native shape."""
    if not ai_configured(db):
        raise AiNotConfigured("AI is not configured yet.")
    name = provider(db)
    chosen = model_name or model(db)
    if name == "openai":
        return _complete_openai(
            api_key(db), chosen, system, prompt, temperature, image
        )
    return _complete_anthropic(
        api_key(db), chosen, system, prompt, temperature, image
    )


def complete_json(
    db: Session,
    prompt: str,
    *,
    system: str = "",
    model_name: str | None = None,
    temperature: float | None = None,
    image: tuple[str, str] | None = None,
) -> dict:
    """A completion that must be a JSON object (the item-ID and
    lookup assists). Code fences are stripped; anything else that
    doesn't parse is a provider error, never a silent {}."""
    text = complete(
        db,
        prompt,
        system=system,
        model_name=model_name,
        temperature=temperature,
        image=image,
    ).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise AiProviderError("AI reply was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise AiProviderError("AI reply was not a JSON object")
    return parsed


# -- web search (the seam's eyes; owner's one-vendor decision, 2026-10-25) ----
#
# The site runs ONE AI vendor for brain and eyes alike: the
# provider's own web search (OpenAI's Responses `web_search`
# tool; Anthropic's server-side web search tool). There is no
# separate search account, key, or setting — search is lit
# exactly when the seam is.
#
# THE RULE the whole design hangs on: a search result is
# ROUTING, never evidence. `web_search` returns only citation
# URLs (plus the cited page's title, for candidate pickers) —
# the provider's answer TEXT is discarded at this boundary and
# no consumer ever treats it as a fact. Consumers fetch the
# chosen page themselves and admit only facts that page
# supports (catalog.grounded's validator). Tracking parameters
# the providers glue onto citation URLs (utm_source=openai and
# kin) are stripped here, before any fetcher sees them.


def _clean_citation_url(url: object) -> str:
    """One citation URL, usable by the site's fetchers: https
    with a real host, tracking parameters removed. "" when the
    citation isn't a fetchable page address at all."""
    if not isinstance(url, str):
        return ""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunparse(parsed._replace(query=urlencode(params)))


def _search_openai(key: str, model_name: str, prompt: str) -> list[dict]:
    """OpenAI Responses API with the web_search tool. Returns
    the raw [{url, title}] citations the reply carried — the
    answer text itself is dropped here, by design."""
    body = _transport(
        "https://api.openai.com/v1/responses",
        {"Authorization": f"Bearer {key}"},
        {
            "model": model_name,
            "tools": [{"type": "web_search"}],
            "input": prompt,
        },
        timeout=_SEARCH_TIMEOUT_SECONDS,
    )
    _note_usage("openai", body)
    if isinstance(body.get("error"), dict):
        raise AiProviderError("AI provider search failed")
    out: list[dict] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            # Newer API revisions attach the result list to the
            # search call itself; annotations below remain the
            # canonical citation path.
            action = item.get("action") or {}
            for source in action.get("sources") or []:
                if isinstance(source, dict) and source.get("url"):
                    out.append(
                        {"url": source["url"], "title": source.get("title") or ""}
                    )
            continue
        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            for note in block.get("annotations") or []:
                if (
                    isinstance(note, dict)
                    and note.get("type") == "url_citation"
                    and note.get("url")
                ):
                    out.append(
                        {"url": note["url"], "title": note.get("title") or ""}
                    )
    return out


def _search_anthropic(key: str, model_name: str, prompt: str) -> list[dict]:
    """Anthropic Messages API with its server-side web search
    tool. Returns the raw [{url, title}] results the search
    blocks carried."""
    body = _transport(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
        {
            "model": model_name,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
            ],
        },
        timeout=_SEARCH_TIMEOUT_SECONDS,
    )
    _note_usage("anthropic", body)
    out: list[dict] = []
    saw_error = False
    for block in body.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        content = block.get("content")
        if isinstance(content, dict) and content.get("type") == (
            "web_search_tool_result_error"
        ):
            saw_error = True
            continue
        for entry in content or []:
            if (
                isinstance(entry, dict)
                and entry.get("type") == "web_search_result"
                and entry.get("url")
            ):
                out.append({"url": entry["url"], "title": entry.get("title") or ""})
    if saw_error and not out:
        raise AiProviderError("AI provider search failed")
    return out


def web_search(db: Session, subject: str, *, max_results: int = 8) -> list[dict]:
    """One web search through the configured provider, for a
    lookup subject ("Matco SPRB4A", "the owner's manual PDF
    for Fluke 17B+"). Returns up to `max_results` citations as
    [{url, title}] — cleaned, deduped, https only, in the order
    the provider cited them. An empty list means the search ran
    and cited nothing usable (consumers degrade honestly; a
    citation-less answer is never dressed up as a result).

    Raises AiNotConfigured while the seam is dark and
    AiProviderError when the provider call fails — callers
    decide which of those their surface tolerates."""
    if not ai_configured(db):
        raise AiNotConfigured("AI is not configured yet.")
    prompt = (
        "Use web search to find pages for this lookup: "
        + subject.strip()
        + "\nPrefer the manufacturer's official pages, then "
        "retailer product pages. Answer in a sentence or two "
        "and cite the pages you used."
    )
    if provider(db) == "openai":
        raw = _search_openai(api_key(db), model(db), prompt)
    else:
        raw = _search_anthropic(api_key(db), model(db), prompt)
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw:
        url = _clean_citation_url(entry.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "title": str(entry.get("title") or "").strip()})
        if len(out) >= max_results:
            break
    return out
