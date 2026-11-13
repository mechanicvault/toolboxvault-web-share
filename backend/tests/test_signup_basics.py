"""Signup basics — the contract as amended by the onboarding
design (owner design 2026-10-31, built 2026-11-07).

Originally (owner directive 2026-10-22) country, currency and
locale were REQUIRED picks at POST /core/signup: missing values
were a 422 before any account existed. The onboarding design
supersedes that: signup asks for login credentials ONLY, so
the basics are now OPTIONAL at the boundary — absent (or, for
country/currency, the empty "no pick" spelling) leaves the
field unset, unset reads as the standing defaults (US / USD /
English) everywhere the values are consumed, and the setup
wizard's basics step collects the real picks afterwards.

What did NOT change: a PROVIDED value is still validated —
unknown country/currency/locale values are a 422 before any
account exists — and the service's own creation path (social
login) still lands with country unset and completes the basics
afterwards, defaulting the currency from the country when one
is given. (The platform color is the gear accent — a local
theme preference like every accent choice on the site; there
is no server field to pin here.)
"""

import itertools

import pytest
from pydantic import ValidationError

from app.modules.core import models as core_models
from app.modules.core import schemas, service

MECHANIC = "mechanic_technician"


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    # service.create_user needs Postgres nextval() for the account
    # number; SQLite has no sequences, so stub the counter (the
    # established pattern — see test_wave3_currency.py).
    counter = itertools.count(901000)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )

BASE = {
    "email": "basics@example.com",
    "name": "Basics User",
    "password": "secret-1",
    "account_types": [MECHANIC],
    "country": "US",
    "currency": "USD",
    "locale": "en",
}


def _post(client, **overrides):
    payload = {**BASE, **overrides}
    return client.post("/api/core/signup", json=payload)


def _no_account(db, email="basics@example.com"):
    return db.query(core_models.User).filter_by(email=email).one_or_none() is None


# -- the required picks -------------------------------------------------------


@pytest.mark.parametrize("missing", ["country", "currency", "locale"])
def test_signup_missing_a_basic_is_created_unset(client, db, missing):
    """Onboarding design (2026-10-31, built 2026-11-07): a basic
    the signup doesn't send is no longer a 422 — the account is
    created with that field UNSET (the service's long-standing
    leniency: unset country/currency/locale read as the
    standing US / USD / English defaults everywhere they're
    consumed) and the wizard's basics step — whose probe reads
    "done" only once country is genuinely set — collects the
    real pick. Fields that WERE sent are stored as sent."""
    payload = {k: v for k, v in BASE.items() if k != missing}
    resp = client.post("/api/core/signup", json=payload)
    assert resp.status_code == 201, resp.text
    stored = db.query(core_models.User).filter_by(email="basics@example.com").one()
    if missing == "country":
        assert stored.country == ""
        assert stored.currency == "USD"
    elif missing == "currency":
        # Currency unset with a country given defaults FROM the
        # country at creation (US -> USD), as it always has.
        assert stored.country == "US"
        assert stored.currency == "USD"
    else:
        assert stored.locale == ""


@pytest.mark.parametrize(
    "overrides",
    [
        {"country": "XX"},  # not a country the chooser offers
        {"country": "USA"},  # alpha-2 only
        {"currency": "XXX"},  # not in core.money.CURRENCIES
        {"locale": ""},
        {"locale": "fr"},  # not a shipped locale
        {"locale": "EN"},  # the pick is exact, not case-folded
    ],
)
def test_signup_invalid_basic_is_422(client, db, overrides):
    resp = _post(client, **overrides)
    assert resp.status_code == 422, resp.text
    assert _no_account(db)


def test_signup_complete_stores_the_basics(client, db):
    resp = _post(client, country="de", currency="eur", locale="es")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Codes are canonicalized (country/currency upper-cased).
    assert body["country"] == "DE"
    assert body["currency"] == "EUR"
    assert body["locale"] == "es"
    stored = db.query(core_models.User).filter_by(email="basics@example.com").one()
    assert (stored.country, stored.currency, stored.locale) == ("DE", "EUR", "es")


def test_signup_schema_defaults_the_basics():
    """The schema no longer requires the basics (onboarding
    design, 2026-10-31): they arrive unset and the service
    applies the standing defaults."""
    req = schemas.SignupRequest(
        email="a@example.com",
        name="A",
        password="secret1",
        account_types=[MECHANIC],
    )
    assert req.country == ""
    assert req.currency == ""
    assert req.locale is None
    # A provided-but-unknown basic still fails the schema.
    with pytest.raises(ValidationError):
        schemas.SignupRequest(
            email="a@example.com",
            name="A",
            password="secret1",
            account_types=[MECHANIC],
            country="XX",
        )


# -- the service stays lenient for the other creation paths -------------------


def test_service_create_user_defaults_currency_from_country(db):
    user = service.create_user(
        db, "oauth-ish@example.com", "Social", "some-password", [MECHANIC],
        country="DE",
    )
    assert user.country == "DE"
    assert user.currency == "EUR"
    assert user.locale == ""


def test_service_create_user_without_country_stays_unset(db):
    user = service.create_user(
        db, "legacy@example.com", "Legacy", "some-password", [MECHANIC]
    )
    assert user.country == ""
    assert user.currency == "USD"
    assert user.locale == ""
