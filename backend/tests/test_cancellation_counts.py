"""Cancellation counts (owner 2026-11-07): the subscription
status-change history behind the admin Accounting report's
cancellations-in-period figure.

Pins:

- RECORDING SEAMS: upsert_subscription records a transition
  only when the status actually changes (creation records the
  first state with from_status None; a same-status re-save
  records nothing); the daily lapse flip records through the
  same door with source "lapse_job".
- EXONERATED PATHS: grants and redeem-style admin grants move
  entitlement without ever touching a subscription's status —
  they create no subscription row and no history.
- THE DEFINITION: a cancellation is a live state (active |
  trialing | past_due) reaching a terminal state (canceled |
  ended), counted once — canceled -> ended is not a second
  cancellation, and a row created in a terminal state never
  counted as live.
- WEBHOOK TRUTH: a full lifecycle driven through the real
  signed webhook handler records the exact transition chain;
  a replayed event and a different event that changes nothing
  both record nothing.
- THE REPORT: build_accounting counts the period's
  cancellations by that definition; a period reaching back
  before recording began (2026-11-07) prints the rider, a
  period fully after recording began prints the bare count.
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.modules.billing import entitlements
from app.modules.billing import models as billing_models
from app.modules.core import models as core_models
from app.modules.reports import admin_reports

WEBHOOK_SECRET = "whsec_test_secret"
NOW = datetime.now(timezone.utc)
PERIOD_END = NOW + timedelta(days=30)


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=f"User {account_number}",
        password_hash="not-a-real-hash",
        account_types=["mechanic_technician"],
        role="user",
        is_operator=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _history(db, user_id=None):
    # The history table carries no sequence column (its
    # created_at has second resolution and several transitions
    # can share a second), so insertion order is read off the
    # test dialect's rowid — the order rows were written.
    rows = db.scalars(
        select(billing_models.SubscriptionStatusChange).order_by(
            text("rowid")
        )
    ).all()
    if user_id is not None:
        rows = [row for row in rows if row.user_id == user_id]
    return [(row.from_status, row.to_status, row.source) for row in rows]


def _cancellations(db, user_id=None):
    return sum(
        1
        for from_status, to_status, _ in _history(db, user_id)
        if entitlements.is_cancellation_change(from_status, to_status)
    )


# -- the definition ---------------------------------------------------------


@pytest.mark.parametrize(
    "from_status,to_status,expected",
    [
        ("active", "canceled", True),
        ("trialing", "canceled", True),
        ("past_due", "canceled", True),
        ("active", "ended", True),
        ("past_due", "ended", True),
        ("canceled", "ended", False),  # the lapse flip after a cancel
        (None, "canceled", False),  # created terminal: never was live
        ("none", "canceled", False),  # checkout placeholder, never live
        ("active", "past_due", False),
        ("past_due", "active", False),
        ("active", "active", False),
    ],
)
def test_cancellation_definition_matrix(from_status, to_status, expected):
    assert (
        entitlements.is_cancellation_change(from_status, to_status)
        is expected
    )


# -- the write seam ---------------------------------------------------------


def test_upsert_records_transitions_only(db):
    user = _make_user(db, "TV-M-002001", "cc-seam@example.com")
    entitlements.upsert_subscription(
        db, user.id, plan_key="pro", status="active", source="stripe"
    )
    assert _history(db, user.id) == [(None, "active", "stripe")]
    # Same facts re-saved (a webhook re-sync of the same state):
    # nothing records.
    entitlements.upsert_subscription(
        db, user.id, plan_key="pro", status="active", source="stripe"
    )
    assert _history(db, user.id) == [(None, "active", "stripe")]
    entitlements.upsert_subscription(
        db, user.id, plan_key="pro", status="canceled", source="stripe"
    )
    assert _history(db, user.id) == [
        (None, "active", "stripe"),
        ("active", "canceled", "stripe"),
    ]
    assert _cancellations(db, user.id) == 1


def test_grants_never_touch_subscription_status(db):
    """Admin grants / trials / free periods write EntitlementGrant
    rows only — the exonerated path: no subscription row, no
    history, before and after the grant."""
    user = _make_user(db, "TV-M-002002", "cc-grant@example.com")
    entitlements.grant_period(
        db,
        user.id,
        plan_key="pro",
        kind="trial",
        source="admin",
        days=14,
    )
    entitlements.create_grant(
        db,
        user.id,
        plan_key="pro",
        kind="free_period",
        source="redeem_code",
        source_ref="CODE-1",
    )
    assert entitlements.get_subscription(db, user.id) is None
    assert _history(db, user.id) == []


def test_lapse_flip_records_once(db):
    canceled_user = _make_user(db, "TV-M-002003", "cc-lapse1@example.com")
    live_user = _make_user(db, "TV-M-002004", "cc-lapse2@example.com")
    past = NOW - timedelta(days=1)
    entitlements.upsert_subscription(
        db,
        canceled_user.id,
        plan_key="pro",
        status="canceled",
        source="stripe",
        current_period_end=past,
    )
    entitlements.upsert_subscription(
        db,
        live_user.id,
        plan_key="pro",
        status="active",
        source="stripe",
        current_period_end=past,
    )
    flipped = entitlements.run_lapse_transitions(db, now=NOW)
    assert flipped == 2
    # canceled -> ended rides the lapse source and is NOT a
    # second cancellation; the created-in-canceled row was
    # never live, so this account has zero cancellations.
    assert _history(db, canceled_user.id) == [
        (None, "canceled", "stripe"),
        ("canceled", "ended", "lapse_job"),
    ]
    assert _cancellations(db, canceled_user.id) == 0
    # active -> ended IS the subscription going terminal.
    assert _history(db, live_user.id) == [
        (None, "active", "stripe"),
        ("active", "ended", "lapse_job"),
    ]
    assert _cancellations(db, live_user.id) == 1


# -- the webhook, driven end to end ------------------------------------------

@pytest.fixture()
def seed_plans(db):
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
        ]
    )
    db.commit()


@pytest.fixture()
def stripe_keys(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_123")
    monkeypatch.setattr(settings, "stripe_publishable_key", "pk_test_123")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "app_base_url", "https://toolboxvault.com")
    return settings


def _sign(payload: bytes) -> str:
    ts = int(time.time())
    signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        f"{ts}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={ts},v1={signature}"


def _post_event(client, event: dict):
    payload = json.dumps(event).encode()
    return client.post(
        "/api/billing/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": _sign(payload),
        },
    )


def _subscription_event(
    event_id, user, *, event_type="customer.subscription.created",
    status="active",
):
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
                "status": status,
                "current_period_end": int(PERIOD_END.timestamp()),
                "trial_end": None,
                "metadata": {
                    "user_id": str(user.id),
                    "plan_key": "pro",
                    "period": "monthly",
                    "bracket_key": "",
                },
                "items": {
                    "data": [
                        {
                            "price": {"id": "price_pro_monthly"},
                            "current_period_end": int(
                                PERIOD_END.timestamp()
                            ),
                        }
                    ]
                },
            }
        },
    }


def _invoice_event(event_id, event_type):
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": f"in_{event_id}",
                "customer": "cus_123",
                "subscription": "sub_123",
                "lines": {
                    "data": [
                        {"period": {"end": int(PERIOD_END.timestamp())}}
                    ]
                },
            }
        },
    }


def _checkout_event(event_id, user):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_123",
                "mode": "subscription",
                "subscription": "sub_123",
                "customer": "cus_123",
                "payment_status": "paid",
                "metadata": {
                    "user_id": str(user.id),
                    "plan_key": "pro",
                    "kind": "subscription",
                },
            }
        },
    }


def test_webhook_lifecycle_records_the_exact_chain(
    client, db, stripe_keys, seed_plans
):
    user = _make_user(db, "TV-M-002005", "cc-hook@example.com")

    # Checkout completes: the placeholder lands at status none.
    assert _post_event(client, _checkout_event("evt_cc_1", user)).status_code == 200
    assert _history(db, user.id) == [(None, "none", "stripe")]
    assert _cancellations(db, user.id) == 0

    # The subscription itself arrives, active.
    assert _post_event(
        client, _subscription_event("evt_cc_2", user)
    ).status_code == 200
    # A payment fails, then the retry succeeds, then fails again.
    assert _post_event(
        client,
        _subscription_event(
            "evt_cc_3", user,
            event_type="customer.subscription.updated", status="past_due",
        ),
    ).status_code == 200
    assert _post_event(
        client, _invoice_event("evt_cc_4", "invoice.paid")
    ).status_code == 200
    assert _post_event(
        client, _invoice_event("evt_cc_5", "invoice.payment_failed")
    ).status_code == 200
    expected = [
        (None, "none", "stripe"),
        ("none", "active", "stripe"),
        ("active", "past_due", "stripe"),
        ("past_due", "active", "stripe"),
        ("active", "past_due", "stripe"),
    ]
    assert _history(db, user.id) == expected

    # A REPLAYED event (same id) is an idempotent no-op…
    assert _post_event(
        client, _invoice_event("evt_cc_5", "invoice.payment_failed")
    ).status_code == 200
    # …and a NEW event that changes nothing records nothing.
    assert _post_event(
        client,
        _subscription_event(
            "evt_cc_6", user,
            event_type="customer.subscription.updated", status="past_due",
        ),
    ).status_code == 200
    assert _history(db, user.id) == expected

    # Deletion: past_due -> canceled is the one cancellation.
    assert _post_event(
        client,
        _subscription_event(
            "evt_cc_7", user,
            event_type="customer.subscription.deleted", status="canceled",
        ),
    ).status_code == 200
    assert _history(db, user.id) == expected + [
        ("past_due", "canceled", "stripe")
    ]
    assert _cancellations(db, user.id) == 1


# -- the report ---------------------------------------------------------------


@pytest.fixture()
def god(db):
    return _make_user(db, "TV-M-002006", "cc-god@example.com")


@pytest.fixture()
def plans(db):
    rows = {}
    for key, name, is_paid, sort_order in (
        ("free", "Free", False, 0),
        ("pro", "Pro", True, 1),
    ):
        plan = billing_models.Plan(
            plan_key=key, name=name, is_paid=is_paid,
            sort_order=sort_order,
        )
        db.add(plan)
        rows[key] = plan
    db.commit()
    entitlements.set_setting(db, "landing.pro_monthly_price", "7.99")
    entitlements.set_setting(db, "landing.pro_yearly_price", "79.99")
    return rows


def _record(db, user, from_status, to_status, when, source="stripe"):
    sub = entitlements.get_subscription(db, user.id)
    if sub is None:
        sub = entitlements.upsert_subscription(
            db, user.id, plan_key="pro", status="active", source="stripe"
        )
    row = billing_models.SubscriptionStatusChange(
        subscription_id=sub.id,
        user_id=user.id,
        from_status=from_status,
        to_status=to_status,
        source=source,
        created_at=when,
    )
    db.add(row)
    db.commit()
    return row


def _period_rows(doc):
    section = doc["sections"][2]
    assert section["label"].startswith("In the period")
    return {row[0]: row for row in section["rows"]}


def test_report_counts_cancellations_in_period(db, god, plans):
    in_user = _make_user(db, "TV-M-002007", "cc-r1@example.com")
    out_user = _make_user(db, "TV-M-002008", "cc-r2@example.com")
    noise_user = _make_user(db, "TV-M-002009", "cc-r3@example.com")
    inside = datetime(2026, 12, 10, tzinfo=timezone.utc)
    outside = datetime(2026, 10, 10, tzinfo=timezone.utc)
    _record(db, in_user, "active", "canceled", inside)
    _record(db, out_user, "past_due", "canceled", outside)
    # In-period rows that are NOT cancellations by the definition.
    _record(db, noise_user, "canceled", "ended", inside)
    _record(db, noise_user, None, "canceled", inside)
    doc = admin_reports.build_accounting(
        db, god, {"start": "2026-12-01", "end": "2026-12-31"}
    )
    assert _period_rows(doc)["Cancellations"][1] == "1"


def test_report_rider_only_when_period_reaches_unrecorded_time(
    db, god, plans
):
    user = _make_user(db, "TV-M-002010", "cc-r4@example.com")
    when = datetime(2026, 12, 10, tzinfo=timezone.utc)
    _record(db, user, "trialing", "canceled", when)

    # Fully after recording began: the bare count, the printed
    # definition, and NO rider.
    doc = admin_reports.build_accounting(
        db, god, {"start": "2026-12-01", "end": "2026-12-31"}
    )
    assert _period_rows(doc)["Cancellations"][1] == "1"
    assert "reaching canceled or ended" in doc["subtitle"]
    assert "counted once" in doc["subtitle"]
    assert "cover only the recorded part" not in doc["subtitle"]

    # Reaching back before recording began: the count stands,
    # WITH the rider — never bare.
    doc = admin_reports.build_accounting(
        db, god, {"start": "2026-01-01", "end": "2026-12-31"}
    )
    assert _period_rows(doc)["Cancellations"][1] == "1"
    assert "cover only the recorded part" in doc["subtitle"]
    assert "were never recorded" in doc["subtitle"]
    assert "can't be counted" not in doc["subtitle"]

    # "From the beginning" reaches unrecorded time too.
    doc = admin_reports.build_accounting(db, god, {"end": "2026-12-31"})
    assert "cover only the recorded part" in doc["subtitle"]


def test_report_day_one_reading(db, god, plans):
    """No history at all (production's day-one state): the row
    exists and reads 0; a period covering the day recording
    began carries the rider, because that day's early hours
    precede the deploy."""
    doc = admin_reports.build_accounting(
        db, god, {"start": "2026-11-07", "end": "2026-11-07"}
    )
    assert _period_rows(doc)["Cancellations"][1] == "0"
    assert "cover only the recorded part" in doc["subtitle"]
