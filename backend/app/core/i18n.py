"""Locale resolution (audit A17, blueprint §16).

One rule everywhere: the user's explicit preference
(users.locale) → the default for their stored country
(Spanish-speaking countries → "es") → English. Only "en" and
"es" ship in v1; anything else resolves to "en".
"""

SUPPORTED = ("en", "es")

# ISO 3166 countries whose default interface language is
# Spanish (neutral business Spanish ships for all of them).
ES_COUNTRIES = {
    "AR", "BO", "CL", "CO", "CR", "CU", "DO", "EC", "ES", "GQ",
    "GT", "HN", "MX", "NI", "PA", "PE", "PR", "PY", "SV", "UY",
    "VE",
}


def resolve_locale(user) -> str:
    """Resolve a user row (or anything with .locale/.country)
    to a shipped locale."""
    pref = (getattr(user, "locale", "") or "").strip().lower()
    if pref in SUPPORTED:
        return pref
    country = (getattr(user, "country", "") or "").strip().upper()
    if country in ES_COUNTRIES:
        return "es"
    return "en"
