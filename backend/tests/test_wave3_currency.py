"""Wave 3 — currency chooser + FX hints.

V1 SEMANTICS (pinned): an account's amounts are IN its currency;
stored amounts never convert. Pins:

- the ONE formatter's outputs (symbol currencies, code-fallback
  currencies, zero-decimal currencies, negatives);
- country/currency: since the signup-basics round (owner
  2026-10-22) both are REQUIRED explicit picks at signup (the form
  auto-follows the country until touched); the service still
  defaults the currency from the country for the paths that don't
  ask (social login), and Profile edits keep the same rule;
- cross-user hints: "≈ $X" appears ONLY when the currencies
  differ AND rates exist for both sides; EUR-base cross-math;
- the FX job: a failed fetch keeps yesterday's rates and reports
  the failure in its summary (the job ledgers the outcome);
  stored rates are never touched by a failed run.
"""

import itertools
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.core import money
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    # service.create_user needs Postgres nextval() for the account
    # number; SQLite has no sequences, so stub the counter (the
    # established pattern — see test_account_settings.py).
    counter = itertools.count(900500)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _make_user(db, account_number, email, *, country="", currency="USD"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="FX User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        country=country,
        currency=currency,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# -- the formatter -----------------------------------------------------------------


def test_formatter_symbol_and_fallback_rules():
    assert money.format_money(Decimal("1234.56"), "USD") == "$1,234.56"
    assert money.format_money(Decimal("1234.56"), "EUR") == "€1,234.56"
    assert money.format_money(Decimal("1234.56"), "GBP") == "£1,234.56"
    # No unambiguous symbol → code after the amount.
    assert money.format_money(Decimal("1234.56"), "CAD") == "1,234.56 CAD"
    assert money.format_money(Decimal("1234.5"), "CHF") == "1,234.50 CHF"
    # Zero-decimal currencies render whole.
    assert money.format_money(Decimal("12345"), "JPY") == "¥12,345"
    assert money.format_money(Decimal("12345.6"), "JPY") == "¥12,346"
    # Negatives lead with the minus.
    assert money.format_money(Decimal("-5"), "USD") == "-$5.00"
    assert money.format_money(Decimal("-5"), "CAD") == "-5.00 CAD"
    # Unknown/absent currency falls back to USD, never crashes.
    assert money.format_money(Decimal("1"), None) == "$1.00"
    assert money.format_money(None, "USD") == "$0.00"


def test_country_currency_defaults():
    assert money.currency_for_country("DE") == "EUR"
    assert money.currency_for_country("US") == "USD"
    assert money.currency_for_country("GB") == "GBP"
    assert money.currency_for_country("") == "USD"
    assert money.normalize_country("de") == "DE"
    assert money.normalize_country("XX") == ""
    assert money.normalize_currency("eur") == "EUR"
    assert money.normalize_currency("XXX") == "USD"


# -- signup + profile wiring ----------------------------------------------------------


def test_signup_with_basics_and_profile_edits(client, db):
    response = client.post(
        "/api/core/signup",
        json={
            "email": "fx-signup@example.com",
            "name": "Franz",
            "password": "secret-1",
            "account_types": [MECHANIC],
            "country": "DE",
            "currency": "EUR",
            "locale": "en",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["country"] == "DE"
    assert body["currency"] == "EUR"
    assert body["locale"] == "en"

    user = db.query(core_models.User).filter_by(email="fx-signup@example.com").one()
    headers = auth_headers(user)
    # Currency is independently changeable afterwards.
    changed = client.patch(
        "/api/core/me", json={"currency": "CHF"}, headers=headers
    )
    assert changed.json()["currency"] == "CHF"
    assert changed.json()["country"] == "DE"
    # A country sent WITHOUT a currency re-defaults the currency.
    moved = client.patch("/api/core/me", json={"country": "GB"}, headers=headers)
    assert moved.json()["country"] == "GB"
    assert moved.json()["currency"] == "GBP"
    # An unknown currency is not applied; the stored one stands.
    bogus = client.patch(
        "/api/core/me", json={"currency": "XXX"}, headers=headers
    )
    assert bogus.json()["currency"] == "GBP"


def test_signup_explicit_currency_wins_over_country(client, db):
    response = client.post(
        "/api/core/signup",
        json={
            "email": "fx-explicit@example.com",
            "name": "Explicit",
            "password": "secret-1",
            "account_types": [MECHANIC],
            "country": "DE",
            "currency": "USD",
            "locale": "es",
        },
    )
    assert response.status_code == 201
    assert response.json()["currency"] == "USD"


def test_money_meta_lists(client, db):
    user = _make_user(db, "TV-M-000501", "fx-meta@example.com")
    body = client.get("/api/core/money/meta", headers=auth_headers(user)).json()
    assert "USD" in body["currencies"] and "EUR" in body["currencies"]
    assert {"code": "DE", "label": "Germany"} in body["countries"]
    assert body["country_currencies"]["DE"] == "EUR"


# -- hints -------------------------------------------------------------------------------


def _seed_rates(db):
    money.store_rates(
        db,
        {
            # EUR per 1 unit: 1 USD = 0.92 EUR; 1 GBP = 1.17 EUR.
            "USD": Decimal("0.92"),
            "GBP": Decimal("1.17"),
        },
        date(2026, 10, 19),
    )


def test_hint_only_when_currencies_differ_and_rates_exist(client, db):
    _seed_rates(db)
    viewer = _make_user(db, "TV-M-000502", "fx-viewer@example.com", currency="USD")
    # Same currency → no hint.
    assert money.convert_hint(db, Decimal("100"), "USD", "USD") is None
    # EUR amount for a USD viewer: 100 EUR = 100/0.92 USD ≈ $108.70.
    assert money.convert_hint(db, Decimal("100"), "EUR", "USD") == "≈ $108.70"
    # GBP → USD cross through the EUR base: 100 * 1.17 / 0.92 ≈ $127.17.
    assert money.convert_hint(db, Decimal("100"), "GBP", "USD") == "≈ $127.17"
    # A currency with NO cached rate → no hint (never guessed).
    assert money.convert_hint(db, Decimal("100"), "CAD", "USD") is None
    assert money.convert_hint(db, Decimal("100"), "USD", "CAD") is None

    hint = client.get(
        "/api/core/money/hint",
        params={"amount": "100", "from_currency": "EUR"},
        headers=auth_headers(viewer),
    )
    assert hint.json() == {"hint": "≈ $108.70", "viewer_currency": "USD"}


def test_hint_endpoint_same_currency_is_null(client, db):
    _seed_rates(db)
    viewer = _make_user(db, "TV-M-000503", "fx-viewer2@example.com", currency="EUR")
    hint = client.get(
        "/api/core/money/hint",
        params={"amount": "50", "from_currency": "EUR"},
        headers=auth_headers(viewer),
    )
    assert hint.json()["hint"] is None


# -- cross-user surfaces carry the SELLER's currency ---------------------------------------


def test_cross_user_serializers_label_seller_currency(db):
    """Marketplace + parts-pool listings are priced in the
    SELLER's currency (v1 semantics); the payload says so, so the
    board can label the amount and hint a conversion."""
    from app.modules.parts import models as part_models
    from app.modules.parts import pool as parts_pool

    seller = _make_user(db, "TV-M-000504", "fx-seller@example.com", currency="EUR")
    part = part_models.Part(
        owner_id=seller.id, title="Alternator", quantity=1,
        asking_price=Decimal("80"), attachments=[],
    )
    view = parts_pool.serialize_listing(part, seller, None)
    assert view["seller_currency"] == "EUR"
    assert view["asking_price"] == Decimal("80")  # never converted


# -- reports outputs ride the same formatter ---------------------------------------------------


def test_reports_money_cells_use_the_owner_currency():
    from decimal import Decimal as D

    from app.modules.reports import exports as report_exports
    from app.modules.reports import service as report_service

    class _Row:
        values = {"price": D("1234.56")}
        in_set_price = False

    column = {"key": "price", "type": "money"}
    assert report_service.format_cell(column, _Row(), "EUR") == "€1,234.56"
    assert report_service.format_cell(column, _Row(), "CAD") == "1,234.56 CAD"
    assert report_service.format_cell(column, _Row()) == "$1,234.56"
    subtotal = {"price_total": "10", "replacement": "20"}
    assert report_exports.row_display_subtotal(
        {"key": "price_total"}, subtotal, "EUR"
    ) == "€10.00"


# -- the FX job ------------------------------------------------------------------------------


def test_fx_job_failure_keeps_stale_rates(db, monkeypatch):
    _seed_rates(db)
    before = money.latest_rate(db, "USD")
    assert before == Decimal("0.92")

    def boom():
        raise ConnectionError("frankfurter unreachable")

    monkeypatch.setattr(money, "fetch_rates", boom)
    summary = money.run_fx_refresh(db)
    assert "fetch failed" in summary
    assert "kept cached rates" in summary
    # Yesterday's rates are untouched.
    assert money.latest_rate(db, "USD") == Decimal("0.92")


def test_fx_job_success_stores_new_rates(db, monkeypatch):
    monkeypatch.setattr(
        money,
        "fetch_rates",
        lambda: ({"USD": Decimal("0.90")}, date(2026, 10, 20)),
    )
    summary = money.run_fx_refresh(db)
    assert "stored 1 rates dated 2026-10-20" in summary
    assert money.latest_rate(db, "USD") == Decimal("0.90")
    # Idempotent for the same date.
    money.run_fx_refresh(db)
    rows = db.query(core_models.FxRate).filter_by(currency="USD").all()
    assert len(rows) == 1
