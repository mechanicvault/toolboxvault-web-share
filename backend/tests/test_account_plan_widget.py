"""Account & Plan Home widget (widget wave 2 build 4): the
widget's data contract.

The widget adds NO endpoint of its own — it reads GET
/api/billing/me, the exact payload Settings → Plan & billing
renders from, plus /core/me for the tier. These tests pin the
facts the widget's honesty rests on:

- the read answers for EVERY seat, the downloads rung included
  (billing is always-on infrastructure; the endpoint carries no
  module gate on purpose — see billing/routes.py);
- items_total IS the free-tier limit's own count
  (entitlements.asset_count — tools + batteries, set-attached
  tools excluded, sold/replaced excluded), never a second
  definition;
- a paid subscription's period end rides the payload verbatim,
  so the widget's renewal tile can only ever show a date the
  record itself carries; an unpaid account's subscription is
  null, so no date can be invented.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.billing import entitlements, models as billing_models
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

NOW = datetime.now(timezone.utc)


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
        ]
    )
    db.commit()


def _make_user(db, email, **kw):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=kw.pop("account_number", f"TV-X-{uuid.uuid4().hex[:6]}"),
        email=email,
        name="Plan Widget User",
        password_hash="not-a-real-hash",
        account_types=["mechanic_technician"],
        **kw,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_tool(db, owner_id, name, **kw):
    tool = inventory_models.Tool(
        id=uuid.uuid4(), owner_id=owner_id, name=name, **kw
    )
    db.add(tool)
    db.commit()
    return tool


def test_billing_me_free_count_is_the_limits_own_count(client, db, user_a):
    for i in range(3):
        _make_tool(db, user_a.id, f"Tool {i}")
    db.add(
        inventory_models.Battery(
            id=uuid.uuid4(), owner_id=user_a.id, name="M18 pack"
        )
    )
    # A sold tool holds no plan slot and counts toward nothing.
    _make_tool(db, user_a.id, "Sold saw", standing="sold")
    db.commit()

    resp = client.get("/api/billing/me", headers=auth_headers(user_a))
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_key"] == "free"
    assert body["plan_name"] == "Free"
    assert body["is_paid"] is False
    assert body["item_limit"] == 20
    # The limit's own counter, consumed verbatim.
    assert body["items_total"] == entitlements.asset_count(db, user_a.id) == 4
    assert body["items_active"] == 4
    # No subscription record -> no date exists for a widget to show.
    assert body["subscription"] is None


def test_billing_me_answers_for_the_downloads_rung(client, db):
    rung = _make_user(db, "rung@example.com", tier="downloads")
    resp = client.get("/api/billing/me", headers=auth_headers(rung))
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_key"] == "free"
    assert body["items_total"] == 0
    assert body["subscription"] is None


def test_billing_me_paid_subscription_carries_its_period_end(client, db, user_a):
    period_end = NOW + timedelta(days=30)
    entitlements.upsert_subscription(
        db,
        user_a.id,
        plan_key="pro",
        status="active",
        source="stripe",
        current_period_end=period_end,
    )
    resp = client.get("/api/billing/me", headers=auth_headers(user_a))
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_name"] == "Pro"
    assert body["is_paid"] is True
    assert body["source"] == "subscription"
    # An unlimited plan carries no limit for a fraction to fake.
    assert body["item_limit"] is None
    sub = body["subscription"]
    assert sub is not None
    assert sub["status"] == "active"
    # SQLite round-trips the timestamp naive; the instant is exact.
    assert datetime.fromisoformat(
        sub["current_period_end"]
    ) == period_end.replace(tzinfo=None)


def test_billing_me_requires_sign_in(client):
    assert client.get("/api/billing/me").status_code == 401
