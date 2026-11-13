"""Stripe wiring (billing, 2026-10-19): code-complete in TEST
posture and completely DARK in production until keys + price ids
exist. These tests pin the contract:

- unconfigured: checkout/portal/credits answer 503
  {code: payments_not_configured}, the webhook 404s, and the
  catalog reports nothing purchasable;
- the webhook verifies REAL Stripe signatures (HMAC, computed the
  way Stripe computes them — the SDK's own verifier runs, nothing
  is mocked at the trust boundary);
- events are idempotent per event id: a redelivery changes nothing;
- subscription events sync the SAME subscription rows the A1
  entitlement resolver reads — active grants the plan, past_due
  holds through period end + the owner's 20-day grace, a
  voluntary cancel ends at period end with NO grace, a
  payment-failed cancel keeps the grace;
- credit purchases bank exactly once — even across different event
  ids about the same checkout session (the ledger ref guard).

The SDK's CREATE calls (Customer / Checkout / Portal) are faked
at the class — no network anywhere in this suite.
"""

import hashlib
import hmac
import itertools
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import stripe

from app.core.config import settings
from app.modules.billing import entitlements, stripe_payments, wallet
from app.modules.billing import models as billing_models
from app.modules.core import models as core_models
from tests.conftest import auth_headers

WEBHOOK_SECRET = "whsec_test_secret"
NOW = datetime.now(timezone.utc)
PERIOD_END = NOW + timedelta(days=30)


@pytest.fixture(autouse=True)
def _seed_plans(db):
    db.add_all(
        [
            billing_models.Plan(
                plan_key="free", name="Free", item_limit=20,
                ai_monthly_credits=0, is_paid=False, sort_order=0,
            ),
            billing_models.Plan(
                plan_key="pro", name="Pro", item_limit=None,
                ai_monthly_credits=0, is_paid=True, sort_order=1,
            ),
            billing_models.Plan(
                plan_key="business", name="Business", item_limit=None,
                ai_monthly_credits=0, is_paid=True, sort_order=2,
            ),
        ]
    )
    db.add_all(
        [
            billing_models.BusinessBracket(
                plan_key="business", up_to_employees=limit,
                bracket_key=key, sort_order=order,
            )
            for order, (limit, key) in enumerate(
                [(5, "up_to_5"), (10, "up_to_10"), (25, "up_to_25"), (None, "unlimited")]
            )
        ]
    )
    db.commit()


@pytest.fixture()
def stripe_keys(monkeypatch):
    """Configure the server-side Stripe keys (test values)."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_123")
    monkeypatch.setattr(settings, "stripe_publishable_key", "pk_test_123")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "app_base_url", "https://toolboxvault.com")
    return settings


class FakeStripeApi:
    """Records the SDK create calls and returns canned objects."""

    def __init__(self):
        self.customer_creates: list[dict] = []
        self.checkout_creates: list[dict] = []
        self.portal_creates: list[dict] = []
        self._counter = itertools.count(1)

    def install(self, monkeypatch):
        monkeypatch.setattr(stripe.Customer, "create", self._customer_create)
        monkeypatch.setattr(
            stripe.checkout.Session, "create", self._checkout_create
        )
        monkeypatch.setattr(
            stripe.billing_portal.Session, "create", self._portal_create
        )
        return self

    def _customer_create(self, **kwargs):
        self.customer_creates.append(kwargs)
        return SimpleNamespace(id=f"cus_fake_{next(self._counter)}")

    def _checkout_create(self, **kwargs):
        self.checkout_creates.append(kwargs)
        n = next(self._counter)
        return SimpleNamespace(
            id=f"cs_fake_{n}", url=f"https://checkout.stripe.test/{n}"
        )

    def _portal_create(self, **kwargs):
        self.portal_creates.append(kwargs)
        return SimpleNamespace(url="https://portal.stripe.test/session")


@pytest.fixture()
def fake_stripe(monkeypatch):
    return FakeStripeApi().install(monkeypatch)


def _make_user(db, email, **kw):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=kw.pop("account_number", f"TV-S-{uuid.uuid4().hex[:6]}"),
        email=email,
        name="Stripe User",
        password_hash="not-a-real-hash",
        account_types=["mechanic_technician"],
        **kw,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _set_prices(db):
    entitlements.set_setting(db, stripe_payments.PRICE_PRO_MONTHLY_KEY, "price_pro_monthly")
    entitlements.set_setting(db, stripe_payments.PRICE_PRO_YEARLY_KEY, "price_pro_yearly")
    entitlements.set_setting(db, stripe_payments.PRICE_BUSINESS_MONTHLY_KEY, "price_biz_monthly")
    entitlements.set_setting(db, stripe_payments.PRICE_BUSINESS_YEARLY_KEY, "price_biz_yearly")
    entitlements.set_setting(
        db,
        stripe_payments.BRACKET_PRICE_MAP_KEY,
        {"up_to_5": "price_bracket_5", "up_to_10": "price_bracket_10"},
    )


def _set_packs(db):
    entitlements.set_setting(
        db,
        stripe_payments.AI_CREDIT_PACKS_KEY,
        [
            {"id": "pack_100", "label": "100 credits", "credits": 100,
             "stripe_price_id": "price_pack_100"},
            {"id": "pack_unpriced", "label": "Mystery pack", "credits": 5,
             "stripe_price_id": ""},
        ],
    )


# -- webhook plumbing ------------------------------------------------------


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    ts = int(time.time())
    signature = hmac.new(
        secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return f"t={ts},v1={signature}"


def _post_event(client, event: dict, secret: str = WEBHOOK_SECRET, sign=True):
    payload = json.dumps(event).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["Stripe-Signature"] = _sign(payload, secret)
    return client.post("/api/billing/webhook", content=payload, headers=headers)


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _subscription_event(
    event_id,
    user,
    *,
    event_type="customer.subscription.created",
    status="active",
    sub_id="sub_123",
    customer="cus_123",
    period_end=PERIOD_END,
    price_id="price_pro_monthly",
    plan_key="pro",
    bracket_key="",
    cancellation_reason=None,
):
    obj = {
        "id": sub_id,
        "customer": customer,
        "status": status,
        "current_period_end": _epoch(period_end),
        "trial_end": None,
        "metadata": {
            "user_id": str(user.id),
            "plan_key": plan_key,
            "period": "monthly",
            "bracket_key": bracket_key,
        },
        "items": {
            "data": [
                {"price": {"id": price_id}, "current_period_end": _epoch(period_end)}
            ]
        },
    }
    if cancellation_reason is not None:
        obj["cancellation_details"] = {"reason": cancellation_reason}
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


def _invoice_event(event_id, event_type, *, customer="cus_123", sub_id="sub_123",
                   period_end=PERIOD_END):
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": f"in_{event_id}",
                "customer": customer,
                "subscription": sub_id,
                "lines": {"data": [{"period": {"end": _epoch(period_end)}}]},
            }
        },
    }


def _activate_pro(client, db, user):
    """Drive the subscription.created event that grants Pro."""
    response = _post_event(client, _subscription_event("evt_activate", user))
    assert response.status_code == 200, response.text
    return response


# -- dark posture ------------------------------------------------------------


def test_unconfigured_everything_is_dark(client, user_a):
    headers = auth_headers(user_a)
    for path, payload in (
        ("/api/billing/checkout", {"plan_key": "pro", "period": "monthly"}),
        ("/api/billing/checkout-credits", {"pack_id": "pack_100"}),
        ("/api/billing/portal", None),
    ):
        response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 503, path
        detail = response.json()["detail"]
        assert detail["code"] == "payments_not_configured"
        assert detail["message"]

    webhook = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=whatever"},
    )
    assert webhook.status_code == 404

    catalog = client.get("/api/billing/catalog", headers=headers)
    assert catalog.status_code == 200
    body = catalog.json()
    assert body["payments_configured"] is False
    assert all(
        not available
        for plan in body["plans"]
        for available in plan["checkout_available"].values()
    )


def test_checkout_without_price_id_is_a_friendly_400(
    client, user_a, stripe_keys, fake_stripe
):
    response = client.post(
        "/api/billing/checkout",
        headers=auth_headers(user_a),
        json={"plan_key": "pro", "period": "monthly"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "pricing_not_configured"
    assert "launch" in detail["message"]
    assert fake_stripe.checkout_creates == []


# -- checkout / portal ---------------------------------------------------------


def test_checkout_creates_customer_lazily_once(
    db, client, user_a, stripe_keys, fake_stripe
):
    _set_prices(db)
    headers = auth_headers(user_a)
    first = client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan_key": "pro", "period": "monthly"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["url"].startswith("https://checkout.stripe.test/")
    assert len(fake_stripe.customer_creates) == 1
    db.refresh(user_a)
    assert user_a.stripe_customer_id is not None
    assert fake_stripe.customer_creates[0]["email"] == user_a.email

    call = fake_stripe.checkout_creates[0]
    assert call["mode"] == "subscription"
    assert call["customer"] == user_a.stripe_customer_id
    assert call["line_items"] == [{"price": "price_pro_monthly", "quantity": 1}]
    assert call["success_url"] == (
        "https://toolboxvault.com/settings/billing?checkout=success"
    )
    assert call["metadata"]["user_id"] == str(user_a.id)
    assert call["subscription_data"]["metadata"]["plan_key"] == "pro"

    second = client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan_key": "pro", "period": "yearly"},
    )
    assert second.status_code == 200
    assert len(fake_stripe.customer_creates) == 1  # reused, never duplicated
    assert fake_stripe.checkout_creates[1]["line_items"] == [
        {"price": "price_pro_yearly", "quantity": 1}
    ]


def test_business_checkout_needs_a_bracket_and_charges_base_plus_bracket(
    db, client, user_a, stripe_keys, fake_stripe
):
    _set_prices(db)
    headers = auth_headers(user_a)
    missing = client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan_key": "business", "period": "monthly"},
    )
    assert missing.status_code == 400
    assert "bracket" in missing.json()["detail"]["message"]

    unknown = client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan_key": "business", "period": "monthly", "bracket": "huge"},
    )
    assert unknown.status_code == 400

    ok = client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan_key": "business", "period": "monthly", "bracket": "up_to_5"},
    )
    assert ok.status_code == 200, ok.text
    assert fake_stripe.checkout_creates[0]["line_items"] == [
        {"price": "price_biz_monthly", "quantity": 1},
        {"price": "price_bracket_5", "quantity": 1},
    ]
    assert fake_stripe.checkout_creates[0]["metadata"]["bracket_key"] == "up_to_5"


def test_business_bracket_without_price_is_pricing_not_configured(
    db, client, user_a, stripe_keys, fake_stripe
):
    _set_prices(db)  # up_to_25 has NO bracket price in the map
    response = client.post(
        "/api/billing/checkout",
        headers=auth_headers(user_a),
        json={"plan_key": "business", "period": "monthly", "bracket": "up_to_25"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "pricing_not_configured"


def test_portal_needs_a_customer_then_works(
    db, client, user_a, stripe_keys, fake_stripe
):
    _set_prices(db)
    headers = auth_headers(user_a)
    early = client.post("/api/billing/portal", headers=headers)
    assert early.status_code == 400
    assert "nothing to manage" in early.json()["detail"]["message"]

    client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan_key": "pro", "period": "monthly"},
    )
    portal = client.post("/api/billing/portal", headers=headers)
    assert portal.status_code == 200
    assert portal.json()["url"] == "https://portal.stripe.test/session"
    assert fake_stripe.portal_creates[0]["customer"] == user_a.stripe_customer_id
    assert fake_stripe.portal_creates[0]["return_url"] == (
        "https://toolboxvault.com/settings/billing"
    )

    me = client.get("/api/billing/me", headers=headers)
    assert me.json()["has_stripe_customer"] is True


# -- webhook: trust boundary ---------------------------------------------------


def test_webhook_rejects_bad_signatures(client, db, user_a, stripe_keys):
    event = _subscription_event("evt_bad_sig", user_a)
    payload = json.dumps(event).encode()
    bad = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": "t=1,v1=deadbeef"},
    )
    assert bad.status_code == 400
    wrong_secret = _post_event(client, event, secret="whsec_somebody_else")
    assert wrong_secret.status_code == 400
    unsigned = _post_event(client, event, sign=False)
    assert unsigned.status_code == 400
    # And nothing leaked into state from any of them.
    assert db.get(billing_models.StripeEvent, "evt_bad_sig") is None
    assert entitlements.resolve_entitlement(db, user_a.id).plan_key == "free"


def test_webhook_accepts_a_real_signature(client, db, user_a, stripe_keys):
    response = _post_event(client, _subscription_event("evt_real_sig", user_a))
    assert response.status_code == 200
    assert response.json() == {"received": True}


def test_failed_signature_records_no_event(client, db, user_a, stripe_keys):
    event = _subscription_event("evt_never_recorded", user_a)
    payload = json.dumps(event).encode()
    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": "t=1,v1=deadbeef"},
    )
    assert response.status_code == 400
    assert db.get(billing_models.StripeEvent, "evt_never_recorded") is None
    assert entitlements.resolve_entitlement(db, user_a.id).plan_key == "free"


# -- webhook: subscription sync ---------------------------------------------------


def test_subscription_event_grants_pro_and_is_idempotent(
    client, db, user_a, stripe_keys
):
    _set_prices(db)
    first = _activate_pro(client, db, user_a)
    assert first.json() == {"received": True}

    ent = entitlements.resolve_entitlement(db, user_a.id)
    assert ent.plan_key == "pro"
    assert ent.source == "subscription"
    row = entitlements.get_subscription(db, user_a.id)
    assert row.stripe_subscription_id == "sub_123"
    assert row.stripe_status == "active"
    assert row.source == "stripe"

    again = _post_event(client, _subscription_event("evt_activate", user_a))
    assert again.status_code == 200
    assert again.json() == {"received": True, "duplicate": True}
    assert entitlements.resolve_entitlement(db, user_a.id).plan_key == "pro"


def test_checkout_completed_links_then_subscription_event_activates(
    client, db, user_a, stripe_keys
):
    _set_prices(db)
    completed = {
        "id": "evt_checkout_done",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_123",
                "mode": "subscription",
                "customer": "cus_123",
                "subscription": "sub_123",
                "payment_status": "paid",
                "metadata": {
                    "user_id": str(user_a.id),
                    "kind": "subscription",
                    "plan_key": "pro",
                    "period": "monthly",
                    "bracket_key": "",
                },
            }
        },
    }
    response = _post_event(client, completed)
    assert response.status_code == 200, response.text
    row = entitlements.get_subscription(db, user_a.id)
    assert row is not None
    assert row.stripe_subscription_id == "sub_123"
    # The success event alone grants NOTHING — the subscription
    # event is the authority (fail-safe by design).
    assert entitlements.resolve_entitlement(db, user_a.id).plan_key == "free"
    db.refresh(user_a)
    assert user_a.stripe_customer_id == "cus_123"

    _activate_pro(client, db, user_a)
    assert entitlements.resolve_entitlement(db, user_a.id).plan_key == "pro"


def test_plan_resolved_from_price_when_metadata_absent(
    client, db, user_a, stripe_keys
):
    _set_prices(db)
    # Checkout already linked the customer (that's how the
    # customer join resolves the user); this event carries no
    # metadata at all, so the PLAN must come from the price
    # reverse map alone.
    user_a.stripe_customer_id = "cus_123"
    db.commit()
    event = _subscription_event("evt_no_metadata", user_a)
    event["data"]["object"]["metadata"] = {}
    response = _post_event(client, event)
    assert response.status_code == 200, response.text
    ent = entitlements.resolve_entitlement(db, user_a.id)
    assert ent.plan_key == "pro"  # via the price reverse map


def test_invoice_paid_keeps_active_and_failed_arms_the_grace_clock(
    client, db, user_a, stripe_keys
):
    _set_prices(db)
    _activate_pro(client, db, user_a)

    paid = _post_event(client, _invoice_event("evt_inv_paid", "invoice.paid"))
    assert paid.status_code == 200
    row = entitlements.get_subscription(db, user_a.id)
    assert row.status == "active"
    assert row.grace_until is None

    failed = _post_event(
        client, _invoice_event("evt_inv_failed", "invoice.payment_failed")
    )
    assert failed.status_code == 200, failed.text
    row = entitlements.get_subscription(db, user_a.id)
    assert row.status == "past_due"
    grace = row.grace_until
    assert grace is not None
    expected = PERIOD_END + timedelta(days=20)
    assert abs((grace.replace(tzinfo=timezone.utc) - expected).total_seconds()) < 2

    # Through the paid period the plan holds as a subscription…
    ent = entitlements.resolve_entitlement(db, user_a.id, now=PERIOD_END - timedelta(days=1))
    assert ent.plan_key == "pro"
    # …through the 20-day grace as subscription_grace…
    ent = entitlements.resolve_entitlement(db, user_a.id, now=PERIOD_END + timedelta(days=10))
    assert ent.plan_key == "pro"
    assert ent.source == "subscription_grace"
    # …and only then lands on Free. Nobody was hard-dropped.
    ent = entitlements.resolve_entitlement(db, user_a.id, now=PERIOD_END + timedelta(days=21))
    assert ent.plan_key == "free"


def test_subscription_updated_past_due_arms_grace(
    client, db, user_a, stripe_keys
):
    _set_prices(db)
    _activate_pro(client, db, user_a)
    response = _post_event(
        client,
        _subscription_event(
            "evt_now_past_due",
            user_a,
            event_type="customer.subscription.updated",
            status="past_due",
        ),
    )
    assert response.status_code == 200, response.text
    ent = entitlements.resolve_entitlement(db, user_a.id, now=PERIOD_END + timedelta(days=19))
    assert ent.plan_key == "pro"
    ent = entitlements.resolve_entitlement(db, user_a.id, now=PERIOD_END + timedelta(days=21))
    assert ent.plan_key == "free"


def _deleted_event(event_id, user, reason):
    return _subscription_event(
        event_id,
        user,
        event_type="customer.subscription.deleted",
        status="canceled",
        cancellation_reason=reason,
    )


def test_voluntary_cancel_ends_at_period_end_without_grace(
    client, db, user_a, stripe_keys
):
    _set_prices(db)
    _activate_pro(client, db, user_a)
    response = _post_event(
        client, _deleted_event("evt_deleted_voluntary", user_a, "cancellation_requested")
    )
    assert response.status_code == 200, response.text
    ent = entitlements.resolve_entitlement(db, user_a.id, now=PERIOD_END - timedelta(days=1))
    assert ent.plan_key == "pro"  # holds through the paid period
    ent = entitlements.resolve_entitlement(db, user_a.id, now=PERIOD_END + timedelta(days=1))
    assert ent.plan_key == "free"  # no grace for a voluntary cancel


def test_payment_failed_cancel_keeps_the_20_day_grace(
    client, db, user_a, stripe_keys
):
    _set_prices(db)
    _activate_pro(client, db, user_a)
    response = _post_event(
        client, _deleted_event("evt_deleted_nonpayment", user_a, "payment_failed")
    )
    assert response.status_code == 200, response.text
    # (Inside the window rather than on its exact edge: webhook
    # period ends arrive as whole-second epochs.)
    ent = entitlements.resolve_entitlement(db, user_a.id, now=PERIOD_END + timedelta(days=19))
    assert ent.plan_key == "pro"
    ent = entitlements.resolve_entitlement(db, user_a.id, now=PERIOD_END + timedelta(days=21))
    assert ent.plan_key == "free"


# -- webhook: AI credit purchases -----------------------------------------------


def _credits_event(event_id, user, *, session_id="cs_pack_1", credits="100"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "mode": "payment",
                "customer": "cus_123",
                "subscription": None,
                "payment_status": "paid",
                "metadata": {
                    "user_id": str(user.id),
                    "kind": "ai_credits",
                    "pack_id": "pack_100",
                    "credits": credits,
                },
            }
        },
    }


def test_credits_checkout_endpoint(db, client, user_a, stripe_keys, fake_stripe):
    _set_packs(db)
    headers = auth_headers(user_a)
    ok = client.post(
        "/api/billing/checkout-credits", headers=headers, json={"pack_id": "pack_100"}
    )
    assert ok.status_code == 200, ok.text
    call = fake_stripe.checkout_creates[0]
    assert call["mode"] == "payment"
    assert call["line_items"] == [{"price": "price_pack_100", "quantity": 1}]
    assert call["metadata"]["credits"] == "100"

    unknown = client.post(
        "/api/billing/checkout-credits", headers=headers, json={"pack_id": "nope"}
    )
    assert unknown.status_code == 400

    unpriced = client.post(
        "/api/billing/checkout-credits",
        headers=headers,
        json={"pack_id": "pack_unpriced"},
    )
    assert unpriced.status_code == 400
    assert unpriced.json()["detail"]["code"] == "pricing_not_configured"


def test_credits_purchase_banks_exactly_once(
    client, db, user_a, stripe_keys
):
    _set_packs(db)
    first = _post_event(client, _credits_event("evt_pack_1", user_a))
    assert first.status_code == 200, first.text
    assert wallet.wallet_view(db, user_a.id)["banked_balance"] == 100

    # Same event redelivered: the event ledger stops it.
    again = _post_event(client, _credits_event("evt_pack_1", user_a))
    assert again.json().get("duplicate") is True
    assert wallet.wallet_view(db, user_a.id)["banked_balance"] == 100

    # A DIFFERENT event about the same session: the wallet
    # ledger's session ref stops it.
    other = _post_event(client, _credits_event("evt_pack_2", user_a))
    assert other.status_code == 200
    assert wallet.wallet_view(db, user_a.id)["banked_balance"] == 100

    # A different session is a different purchase and banks again.
    _post_event(client, _credits_event("evt_pack_3", user_a, session_id="cs_pack_2"))
    assert wallet.wallet_view(db, user_a.id)["banked_balance"] == 200


def test_credits_not_banked_until_payment_settles(
    client, db, user_a, stripe_keys
):
    _set_packs(db)
    event = _credits_event("evt_pack_unpaid", user_a)
    event["data"]["object"]["payment_status"] = "unpaid"
    response = _post_event(client, event)
    assert response.status_code == 200
    assert wallet.wallet_view(db, user_a.id)["banked_balance"] == 0


# -- catalog + admin settings -----------------------------------------------------


def test_catalog_reflects_operator_pricing(db, client, user_a, stripe_keys):
    headers = auth_headers(user_a)
    before = client.get("/api/billing/catalog", headers=headers).json()
    assert before["payments_configured"] is True
    pro = next(p for p in before["plans"] if p["plan_key"] == "pro")
    assert pro["checkout_available"] == {"monthly": False, "yearly": False}

    _set_prices(db)
    _set_packs(db)
    after = client.get("/api/billing/catalog", headers=headers).json()
    pro = next(p for p in after["plans"] if p["plan_key"] == "pro")
    assert pro["checkout_available"] == {"monthly": True, "yearly": True}
    business = next(p for p in after["plans"] if p["plan_key"] == "business")
    assert business["checkout_available"]["monthly"] is True
    bracket = next(b for b in after["brackets"] if b["bracket_key"] == "up_to_5")
    assert bracket["price_configured"] is True
    bracket = next(b for b in after["brackets"] if b["bracket_key"] == "up_to_25")
    assert bracket["price_configured"] is False
    packs = {p["id"]: p for p in after["ai_credit_packs"]}
    assert packs["pack_100"]["purchasable"] is True
    assert packs["pack_unpriced"]["purchasable"] is False
    # Price ids never leak to the browser.
    assert "price_pro_monthly" not in json.dumps(after)


def test_admin_settings_stripe_round_trip(db, client, stripe_keys):
    operator = _make_user(db, "op@example.com", is_operator=True)
    headers = auth_headers(operator)
    put = client.put(
        "/api/admin/settings",
        headers=headers,
        json={
            "stripe_price_pro_monthly": "price_pro_monthly",
            "stripe_price_business_brackets": {"up_to_5": "price_bracket_5"},
            "stripe_ai_credit_packs": [
                {"id": "pack_100", "label": "100 credits", "credits": 100,
                 "stripe_price_id": "price_pack_100"}
            ],
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["stripe"]["configured"] is True
    assert body["stripe"]["price_pro_monthly"] == "price_pro_monthly"
    assert body["stripe"]["price_business_brackets"] == {"up_to_5": "price_bracket_5"}
    assert body["stripe"]["ai_credit_packs"][0]["credits"] == 100

    got = client.get("/api/admin/settings", headers=headers)
    assert got.json()["stripe"]["price_pro_monthly"] == "price_pro_monthly"

    # And the pricing the operator just set is immediately live
    # for checkout decisions (no deploy, no restart).
    catalog = stripe_payments.catalog_view(db)
    pro = next(p for p in catalog["plans"] if p["plan_key"] == "pro")
    assert pro["checkout_available"]["monthly"] is True


def test_admin_settings_stripe_requires_operator(client, user_a):
    response = client.put(
        "/api/admin/settings",
        headers=auth_headers(user_a),
        json={"stripe_price_pro_monthly": "price_x"},
    )
    assert response.status_code == 403

