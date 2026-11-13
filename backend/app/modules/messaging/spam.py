"""The anti-spam firewall (owner, 2026-10-19 16:57).

A shared core service: messaging consumes it today; the forum and
the for-sale listings consume the same screen when they land, so
the rules live in exactly one place. Everything tunable is an
Admin → Settings value (the `spam.config` system setting — a JSON
dict merged over the defaults below, edited through the admin
settings surface and audit-logged there like every other setting).

THE SCREEN, in the order a message meets it:

  1. Trust-tiered RATE LIMITS. A sender's tier comes from account
     age, paid-plan resolution (billing's resolver — a TRIAL never
     raises a tier: trial accounts are the spam vector), and
     completed interactions (a provider seam, below — 0 until
     the reputation build registers its counter). Thread opens
     and messages each have per-hour and per-day caps per tier,
     counted from the tables (never process memory, so a restart
     is not an amnesty).
  2. CONTENT screen of the body: links are extracted; a link to a
     blocklisted domain holds the message for moderation; a lure
     pattern (gift cards, crypto, "verify your account", …) holds
     it too. An ordinary link passes but FLAGS the message so the
     UI renders it behind a warning.
  3. DUPLICATE-BLAST detection: a near-identical body reaching
     the Nth distinct recipient inside the window is held for
     moderation instead of delivered. Similarity is a token-set
     Jaccard over a normalized body — cheap, dialect-free, and
     honest at marketplace scale.

Held is never dropped: the sender sees the message in their own
thread view marked as under review, moderators work it from the
queue (release / discard), and the recipient sees nothing unless
it is released.

SERVICE INTERFACE (stable; bump the messaging manifest version
on change):
  - get_config(db) / public_config_view(db) — effective config.
  - trust_tier(db, user) -> int (0..3).
  - register_interaction_counter(fn) — the reputation seam.
  - check_thread_budget(db, user) / check_message_budget(db, user)
    -> friendly refusal string or None. Callers turn a refusal
    into a 429.
  - screen_body(db, sender_id, body, *, exclude_thread_id=None)
    -> (status, flags): "sent" or "held", plus the flag list.
"""

import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.messaging import models

CONFIG_KEY = "spam.config"

# Seeded defaults (the Admin → Settings spam panel edits the
# `spam.config` setting, which overrides these key by key).
DEFAULT_BLOCKED_DOMAINS: tuple[str, ...] = (
    "bit.ly",
    "tinyurl.com",
    "goo.gl",
    "rb.gy",
    "cutt.ly",
    "shorturl.at",
    "t.ly",
    "is.gd",
    "rebrand.ly",
    "ow.ly",
)
DEFAULT_LURE_PATTERNS: tuple[str, ...] = (
    r"gift\s*cards?",
    r"\bcrypto\b",
    r"verify your account",
    r"confirm your (password|account)",
    r"wire (me|the money|transfer)",
    r"cash\s?app",
    r"zelle me",
    r"send (me )?(\$|usd|money|payment) (first|upfront|before)",
    r"double your (money|bitcoin)",
    r"investment opportunity",
    r"dear (customer|user|friend)",
    r"your account (has been|will be) (suspended|locked|closed)",
)

# Rate budget per tier per window. Tier ladder (see trust_tier):
# 0 brand-new free, 1 a week old, 2 a month old or paying, 3 an
# established paying account or a proven trader.
DEFAULT_TIERS: dict[str, dict[str, int]] = {
    "0": {
        "new_threads_per_hour": 2,
        "new_threads_per_day": 5,
        "messages_per_hour": 20,
        "messages_per_day": 100,
    },
    "1": {
        "new_threads_per_hour": 5,
        "new_threads_per_day": 15,
        "messages_per_hour": 60,
        "messages_per_day": 300,
    },
    "2": {
        "new_threads_per_hour": 10,
        "new_threads_per_day": 40,
        "messages_per_hour": 150,
        "messages_per_day": 800,
    },
    "3": {
        "new_threads_per_hour": 20,
        "new_threads_per_day": 100,
        "messages_per_hour": 400,
        "messages_per_day": 2000,
    },
}

DEFAULT_CONFIG: dict = {
    "blast_threshold": 3,
    "blast_window_minutes": 60,
    "blast_similarity": 0.85,
    "blocked_domains": list(DEFAULT_BLOCKED_DOMAINS),
    "lure_patterns": list(DEFAULT_LURE_PATTERNS),
    "tiers": {tier: dict(caps) for tier, caps in DEFAULT_TIERS.items()},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def get_config(db: Session) -> dict:
    """The effective firewall config: the operator's stored
    `spam.config` merged over the seeded defaults (per key, and
    per tier per cap, so a partial edit never zeroes the rest)."""
    from app.modules.billing import entitlements

    stored = entitlements.get_setting(db, CONFIG_KEY, None)
    config = {
        **DEFAULT_CONFIG,
        "tiers": {t: dict(c) for t, c in DEFAULT_TIERS.items()},
    }
    if isinstance(stored, dict):
        for key, value in stored.items():
            if key == "tiers" and isinstance(value, dict):
                for tier, caps in value.items():
                    if tier in config["tiers"] and isinstance(caps, dict):
                        config["tiers"][tier].update(
                            {k: v for k, v in caps.items() if k in config["tiers"][tier]}
                        )
            elif key in config:
                config[key] = value
    return config


# -- trust tiers -------------------------------------------------------------

# The completed-interactions seam: the reputation build registers
# a counter fn(db, user_id) -> int (completed deals), and tiers
# credit it. Until then every account reads 0.
_interaction_counters: list[Callable] = []


def register_interaction_counter(fn: Callable) -> None:
    if fn not in _interaction_counters:
        _interaction_counters.append(fn)


def completed_interactions(db: Session, user_id: uuid.UUID) -> int:
    total = 0
    for fn in _interaction_counters:
        try:
            total += int(fn(db, user_id) or 0)
        except Exception:
            continue
    return total


def trust_tier(db: Session, user) -> int:
    """The sender's trust tier (0..3).

    Age lays the base: under a week = 0, under a month = 1, older
    = 2. A PAID plan lifts the base to at least 2, and to 3 once
    the account is also a week old — but only from a paying
    source: billing's resolver names a trial "trial", and a trial
    NEVER raises a tier (owner's spam reasoning, 2026-10-19:
    trials are what spammers farm). Completed interactions speak
    for themselves: 5+ lifts to 2, 20+ to 3, plan or no plan.
    """
    created = _aware(getattr(user, "created_at", None)) or _now()
    age_days = max(0, (_now() - created).days)
    tier = 0 if age_days < 7 else 1 if age_days < 30 else 2

    from app.modules.billing import entitlements

    entitlement = entitlements.resolve_entitlement(db, user.id)
    paying = bool(entitlement.is_paid) and entitlement.source != "trial"
    if paying:
        tier = max(tier, 2)
        if age_days >= 7:
            tier = 3
    completed = completed_interactions(db, user.id)
    if completed >= 20:
        tier = 3
    elif completed >= 5:
        tier = max(tier, 2)
    return tier


def tier_caps(db: Session, user) -> dict[str, int]:
    config = get_config(db)
    return config["tiers"][str(trust_tier(db, user))]


# -- rate budgets --------------------------------------------------------------


def _thread_count_since(db: Session, user_id: uuid.UUID, since: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(models.MessageThread.id)).where(
                models.MessageThread.created_by_id == user_id,
                models.MessageThread.created_at >= since,
            )
        )
        or 0
    )


def check_thread_budget(db: Session, user) -> str | None:
    """Friendly refusal when the sender is out of new-thread
    budget, else None. Counts REAL opens from the table."""
    caps = tier_caps(db, user)
    now = _now()
    hour = _thread_count_since(db, user.id, now - timedelta(hours=1))
    if hour >= caps["new_threads_per_hour"]:
        return (
            "You're starting conversations too quickly — please wait "
            "a bit before messaging someone new."
        )
    day = _thread_count_since(db, user.id, now - timedelta(days=1))
    if day >= caps["new_threads_per_day"]:
        return (
            "You've reached today's limit for starting new "
            "conversations. It resets tomorrow."
        )
    return None


def check_message_budget(db: Session, user) -> str | None:
    caps = tier_caps(db, user)
    now = _now()
    base = select(func.count(models.Message.id)).where(
        models.Message.sender_id == user.id,
        models.Message.status != "discarded",
    )
    hour = int(
        db.scalar(base.where(models.Message.created_at >= now - timedelta(hours=1)))
        or 0
    )
    if hour >= caps["messages_per_hour"]:
        return "You're sending messages too quickly — please slow down a little."
    day = int(
        db.scalar(base.where(models.Message.created_at >= now - timedelta(days=1)))
        or 0
    )
    if day >= caps["messages_per_day"]:
        return "You've reached today's message limit. It resets tomorrow."
    return None


# -- content screen ------------------------------------------------------------

_URL_RE = re.compile(r"https?://([^\s/]+)|www\.([^\s/]+)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9$]+")


def extract_domains(body: str) -> list[str]:
    """The domains a body links to (hostnames, lowercased, port
    and userinfo stripped) — the blocklist compares against these."""
    domains: list[str] = []
    for match in _URL_RE.finditer(body or ""):
        host = (match.group(1) or match.group(2) or "").lower()
        host = host.split("@")[-1].split(":")[0].rstrip(".")
        if host:
            domains.append(host)
    return domains


def has_link(body: str) -> bool:
    return bool(_URL_RE.search(body or ""))


def _domain_blocked(domain: str, blocked: list[str]) -> bool:
    """Exact match or a subdomain of a listed domain."""
    return any(domain == item or domain.endswith("." + item) for item in blocked)


def _normalize(body: str) -> str:
    return " ".join(_TOKEN_RE.findall((body or "").lower()))


def _similarity(a: str, b: str) -> float:
    """Token-set Jaccard over normalized bodies. Identical
    normalized text = 1.0; two empty bodies never count as a
    blast (they carry nothing to spread)."""
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _blast_reached(
    db: Session,
    sender_id: uuid.UUID,
    body: str,
    config: dict,
    *,
    exclude_thread_id: uuid.UUID | None,
) -> bool:
    """True when this body is the Nth near-identical one the
    sender has aimed at DISTINCT recipients inside the window.
    Only delivered-or-held messages count (shadow messages never
    reached anyone; removed/discarded are a moderator's story,
    already told)."""
    threshold = int(config["blast_threshold"])
    if threshold <= 1:
        return False
    window_start = _now() - timedelta(minutes=int(config["blast_window_minutes"]))
    rows = list(
        db.execute(
            select(
                models.Message.thread_id,
                models.Message.body,
                models.MessageThread.participant_low_id,
                models.MessageThread.participant_high_id,
            )
            .join(
                models.MessageThread,
                models.MessageThread.id == models.Message.thread_id,
            )
            .where(
                models.Message.sender_id == sender_id,
                models.Message.status.in_(("sent", "held")),
                models.Message.created_at >= window_start,
            )
        ).all()
    )
    normalized = _normalize(body)
    similarity_floor = float(config["blast_similarity"])
    recipients: set[uuid.UUID] = set()
    for thread_id, other_body, low_id, high_id in rows:
        if exclude_thread_id is not None and thread_id == exclude_thread_id:
            continue
        if _similarity(normalized, _normalize(other_body)) >= similarity_floor:
            recipients.add(low_id if high_id == sender_id else high_id)
    # The current send is one more distinct recipient (the caller
    # guarantees the current thread's recipient is not already in
    # the set only when it is a genuinely new target — counting the
    # current thread's recipient unconditionally is the honest
    # read: the same text to the same person twice is a
    # conversation, and the caller excludes the current thread).
    return len(recipients) + 1 >= threshold


def screen_body(
    db: Session,
    sender_id: uuid.UUID,
    body: str,
    *,
    current_recipient_id: uuid.UUID | None = None,
    exclude_thread_id: uuid.UUID | None = None,
) -> tuple[str, list[str]]:
    """Screen one outgoing body. Returns (status, flags):
    ("held", [...]) when the firewall holds it for moderation,
    ("sent", flags) when it may be delivered. Flags always name
    what the screen saw: "link" for any external link,
    "blocked_domain:<domain>", "lure" for a lure pattern, "blast"
    for a duplicate blast."""
    config = get_config(db)
    flags: list[str] = []
    domains = extract_domains(body)
    if domains:
        flags.append("link")
    blocked = [
        str(d).lower().strip() for d in config.get("blocked_domains", []) if str(d).strip()
    ]
    hit = next((d for d in domains if _domain_blocked(d, blocked)), None)
    if hit is not None:
        return "held", [*flags, f"blocked_domain:{hit}"]
    for pattern in config.get("lure_patterns", []):
        try:
            if re.search(str(pattern), body or "", re.IGNORECASE):
                return "held", [*flags, "lure"]
        except re.error:
            continue  # a broken operator pattern must never break sending
    if current_recipient_id is not None and _blast_reached(
        db, sender_id, body, config, exclude_thread_id=exclude_thread_id
    ):
        return "held", [*flags, "blast"]
    return "sent", flags
