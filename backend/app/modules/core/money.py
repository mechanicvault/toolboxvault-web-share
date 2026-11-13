"""Money + currency (core, wave 3, 2026-10-20).

V1 SEMANTICS — read this before touching any money surface:

An account's amounts are IN the account's own currency
(users.currency). A $100 tool on a USD account and a €100 tool on
an EUR account are both stored as the bare number 100; the
currency is a property of the ACCOUNT, not of the amount. Stored
amounts are NEVER converted — conversion would silently rewrite
history every time a rate moved.

What the currency decides:

1. How the owner's own money RENDERS — through the ONE formatter
   in this module (format_money), mirrored by the frontend's one
   helper (frontend/src/lib/money.ts). No surface formats money
   by hand.
2. Cross-user surfaces (marketplace board, parts pool, public
   profiles, shared previews) LABEL amounts with the SELLER's
   currency code, and when the viewer's currency differs, add an
   APPROXIMATE converted hint "≈ $X" from the fx_rates cache.
   Hints are display only, always derived from the cached rate,
   and absent when no rate exists — never guessed.

Rates: the ECB publishes reference rates with EUR as base;
frankfurter.app mirrors them free with no key. The daily job
(run_fx_jobs) stores one row per (currency, date): rate = units
of EUR per 1 unit of the currency... inverted at write time from
frankfurter's "1 EUR = X currency" so cross-math is a single
multiply: amount_in_B = amount_in_A * rate_A / rate_B where
rate_X means "EUR per 1 X". EUR itself stores rate 1.
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import models

logger = logging.getLogger(__name__)

# The sane currency list the settings chooser offers (ISO 4217).
# Deliberately the currencies of the tool trade's main markets —
# extend the tuple, never fork it.
CURRENCIES: tuple[str, ...] = (
    "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "JPY", "SEK",
    "NOK", "DKK", "PLN", "CZK", "HUF", "MXN", "BRL", "ZAR", "INR",
    "CNY", "KRW", "SGD", "HKD", "AED", "ILS", "TRY",
)

# Country (ISO 3166-1 alpha-2) → default currency. Picking a
# country at signup / in Profile defaults the currency from here;
# the user may then change the currency independently.
COUNTRY_CURRENCIES: dict[str, str] = {
    "US": "USD", "GB": "GBP", "CA": "CAD", "AU": "AUD", "NZ": "NZD",
    "CH": "CHF", "JP": "JPY", "SE": "SEK", "NO": "NOK", "DK": "DKK",
    "PL": "PLN", "CZ": "CZK", "HU": "HUF", "MX": "MXN", "BR": "BRL",
    "ZA": "ZAR", "IN": "INR", "CN": "CNY", "KR": "KRW", "SG": "SGD",
    "HK": "HKD", "AE": "AED", "IL": "ILS", "TR": "TRY",
    # The eurozone.
    "AT": "EUR", "BE": "EUR", "DE": "EUR", "ES": "EUR", "FI": "EUR",
    "FR": "EUR", "GR": "EUR", "IE": "EUR", "IT": "EUR", "NL": "EUR",
    "PT": "EUR", "EE": "EUR", "LV": "EUR", "LT": "EUR", "SK": "EUR",
    "SI": "EUR", "HR": "EUR", "CY": "EUR", "MT": "EUR", "LU": "EUR",
}

# Countries the signup / profile chooser offers (alpha-2 → label).
COUNTRIES: tuple[tuple[str, str], ...] = (
    ("US", "United States"), ("CA", "Canada"), ("MX", "Mexico"),
    ("GB", "United Kingdom"), ("IE", "Ireland"), ("DE", "Germany"),
    ("FR", "France"), ("ES", "Spain"), ("IT", "Italy"),
    ("NL", "Netherlands"), ("BE", "Belgium"), ("AT", "Austria"),
    ("CH", "Switzerland"), ("SE", "Sweden"), ("NO", "Norway"),
    ("DK", "Denmark"), ("FI", "Finland"), ("PL", "Poland"),
    ("CZ", "Czechia"), ("HU", "Hungary"), ("PT", "Portugal"),
    ("GR", "Greece"), ("HR", "Croatia"), ("EE", "Estonia"),
    ("LV", "Latvia"), ("LT", "Lithuania"), ("SK", "Slovakia"),
    ("SI", "Slovenia"), ("AU", "Australia"), ("NZ", "New Zealand"),
    ("JP", "Japan"), ("CN", "China"), ("HK", "Hong Kong"),
    ("SG", "Singapore"), ("KR", "South Korea"), ("IN", "India"),
    ("BR", "Brazil"), ("ZA", "South Africa"), ("AE", "United Arab Emirates"),
    ("IL", "Israel"), ("TR", "Türkiye"),
)

# Symbols for the currencies that have an unambiguous one; every
# other currency renders "1,234.56 CODE" (the fallback rule).
SYMBOLS: dict[str, str] = {
    "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥",
    "INR": "₹", "KRW": "₩", "BRL": "R$", "PLN": "zł", "ILS": "₪",
    "TRY": "₺", "ZAR": "R",
}

# Zero-decimal currencies (amounts render whole).
ZERO_DECIMAL = frozenset({"JPY", "KRW", "HUF"})

DEFAULT_CURRENCY = "USD"


def normalize_currency(code: str | None) -> str:
    """A stored/sent currency, canonical: a known ISO code or the
    USD default. Unknown codes never land on an account."""
    candidate = (code or "").strip().upper()
    return candidate if candidate in CURRENCIES else DEFAULT_CURRENCY


def normalize_country(code: str | None) -> str:
    """A stored/sent country: a known alpha-2 or "" (unset)."""
    candidate = (code or "").strip().upper()
    known = {c for c, _ in COUNTRIES}
    return candidate if candidate in known else ""


def currency_for_country(country: str | None) -> str:
    return COUNTRY_CURRENCIES.get(normalize_country(country), DEFAULT_CURRENCY)


def format_money(amount, currency: str | None) -> str:
    """THE formatter. Every backend money string goes through
    here (the frontend mirrors it exactly):

    - symbol currencies: "$1,234.56" / "€1,234.56" (symbol first,
      no space);
    - other currencies: "1,234.56 CAD" (code after, one space);
    - zero-decimal currencies render whole: "¥12,345";
    - negatives lead with "-": "-$5.00".
    """
    code = normalize_currency(currency)
    value = Decimal(str(amount if amount is not None else 0))
    places = 0 if code in ZERO_DECIMAL else 2
    quantized = value.quantize(Decimal("1") if places == 0 else Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    digits = f"{abs(quantized):,.{places}f}"
    symbol = SYMBOLS.get(code)
    if symbol:
        return f"{sign}{symbol}{digits}"
    return f"{sign}{digits} {code}"


# -- the rate cache -----------------------------------------------------------


def latest_rate(db: Session, currency: str) -> Decimal | None:
    """The newest cached EUR-per-unit rate for a currency (EUR
    itself is definitionally 1 and needs no row)."""
    code = normalize_currency(currency)
    if code == "EUR":
        return Decimal("1")
    row = db.scalars(
        select(models.FxRate)
        .where(models.FxRate.currency == code)
        .order_by(models.FxRate.rate_date.desc())
        .limit(1)
    ).first()
    return Decimal(row.rate) if row is not None else None


def convert_hint(
    db: Session,
    amount,
    from_currency: str | None,
    to_currency: str | None,
) -> str | None:
    """The approximate converted hint for a cross-currency view:
    "≈ $123.45" in the VIEWER's currency, or None when the
    currencies match or either rate is missing. DISPLAY ONLY —
    the stored amount is never touched."""
    source = normalize_currency(from_currency)
    target = normalize_currency(to_currency)
    if source == target or amount is None:
        return None
    rate_from = latest_rate(db, source)
    rate_to = latest_rate(db, target)
    if rate_from is None or rate_to is None or rate_to == 0:
        return None
    converted = Decimal(str(amount)) * rate_from / rate_to
    return "≈ " + format_money(converted, target)


def store_rates(db: Session, rates: dict[str, Decimal], rate_date: date) -> int:
    """Write one day's rates (idempotent per currency+date: a
    re-run replaces the day's rows). Returns rows written."""
    written = 0
    for code, rate in rates.items():
        code = normalize_currency(code)
        if code == "EUR":
            continue  # EUR is the base; its rate is definitionally 1
        existing = db.scalars(
            select(models.FxRate).where(
                models.FxRate.currency == code,
                models.FxRate.rate_date == rate_date,
            )
        ).first()
        if existing is None:
            db.add(models.FxRate(currency=code, rate=rate, rate_date=rate_date))
        else:
            existing.rate = rate
        written += 1
    db.commit()
    return written


FRANKFURTER_URL = "https://api.frankfurter.app/latest?from=EUR"


def fetch_rates() -> tuple[dict[str, Decimal], date]:
    """Fetch the ECB reference rates (via frankfurter.app, free,
    no key). frankfurter quotes "1 EUR = X currency"; we store
    the inverse (EUR per 1 unit) so convert math is one multiply.
    Raises on any failure — the job keeps yesterday's rows."""
    import json
    import urllib.request

    request = urllib.request.Request(
        FRANKFURTER_URL, headers={"User-Agent": "ToolboxVault/1.0 fx-job"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rates = {
        code: (Decimal("1") / Decimal(str(value)))
        for code, value in (payload.get("rates") or {}).items()
        if value
    }
    if not rates:
        raise ValueError("frankfurter returned no rates")
    rate_date = date.fromisoformat(payload.get("date") or date.today().isoformat())
    return rates, rate_date


def run_fx_refresh(db: Session) -> str:
    """The daily job's seam: fetch + store. A FAILED fetch keeps
    the existing (stale) rates — the hints keep working off
    yesterday's numbers — and the failure is LOGGED (here and in
    the job run's summary line, which Admin → Settings shows).
    The refresh is best-effort by design: a rate source being
    down for a day is routine, not an incident, so the job
    reports the outcome instead of raising."""
    try:
        rates, rate_date = fetch_rates()
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("FX rate fetch failed; keeping cached rates: %s", exc)
        return f"fx rates: fetch failed ({type(exc).__name__}: {exc}); kept cached rates"
    written = store_rates(db, rates, rate_date)
    return f"fx rates: stored {written} rates dated {rate_date.isoformat()}"


