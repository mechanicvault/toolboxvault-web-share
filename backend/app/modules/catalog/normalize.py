"""Normalization for catalog keys and value comparison (wave 4).

The catalog is keyed by (brand, model) as PEOPLE type them, so
matching must forgive case, punctuation and corporate suffixes
without ever merging genuinely different products: "Matco Tools"
and "MATCO" are one brand; "Mac Tools" and "Matco" must NEVER
collide (the importer's hard rule, applied here too — suffix
stripping only removes trailing corporate filler, it never
truncates a brand's distinguishing stem).
"""

import re
from decimal import Decimal, InvalidOperation

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Trailing corporate filler dropped from BRAND names only —
# "Matco Tools" -> "matco", "Snap-on" -> "snap on". A brand that
# IS one of these words keeps it (the stem must survive).
_BRAND_SUFFIXES = frozenset(
    {
        "tools",
        "tool",
        "inc",
        "corp",
        "corporation",
        "incorporated",
        "llc",
        "ltd",
        "co",
        "company",
        "usa",
    }
)


def norm_text(value: str | None) -> str:
    """Casefold, punctuation -> spaces, collapse whitespace."""
    if not value:
        return ""
    folded = str(value).casefold()
    return " ".join(_NON_ALNUM.sub(" ", folded).split())


def norm_brand(value: str | None) -> str:
    tokens = norm_text(value).split()
    while len(tokens) > 1 and tokens[-1] in _BRAND_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def norm_model(value: str | None) -> str:
    return norm_text(value)


# Manufacturer CODES a maker's own structured data sometimes
# carries instead of the brand name people know (C-08, Deep
# Audit Round 2: DeWALT product pages carry brand "DW", and the
# miner passed it straight into the form's Brand field). Only
# codes ACTUALLY OBSERVED on a live page belong here — this is
# not a directory; add a row only when a proof surfaces one.
BRAND_CODE_ALIASES: dict[str, str] = {
    "dw": "DeWalt",
}


def canonical_brand(value: str | None) -> str:
    """The user-facing brand for a value read off a page: a
    known manufacturer code resolves to the real brand name;
    anything else passes through untouched."""
    if not value:
        return ""
    return BRAND_CODE_ALIASES.get(norm_text(value), str(value).strip())


def resolve_brand(extracted: str | None, typed: str = "") -> str:
    """The brand a lookup result should carry. When the page's
    brand is a manufacturer code, the name the USER typed wins
    over the code's expansion (they know their brand; the code
    is the only part in doubt); with nothing typed, the code
    resolves through BRAND_CODE_ALIASES. A real brand name the
    page states is never overridden."""
    extracted = (extracted or "").strip()
    if norm_text(extracted) in BRAND_CODE_ALIASES:
        typed = (typed or "").strip()
        return typed if typed else BRAND_CODE_ALIASES[norm_text(extracted)]
    return extracted


def norm_value(value: str | None) -> str:
    """Comparison form for a spec field value (category, size)."""
    return norm_text(value)


def norm_upc(value: str | None) -> str:
    """Digits only — UPCs arrive with spaces/dashes from scanners
    and packaging; the stored form is compared digit-to-digit."""
    if not value:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def norm_money(value) -> str | None:
    """Canonical comparison form for a money field (MSRP): the
    2-decimal string, or None when the value isn't a number."""
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return str(amount.quantize(Decimal("0.01")))
