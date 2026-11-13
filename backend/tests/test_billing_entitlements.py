"""Entitlement engine (billing module, Phase A1): one resolver folds
subscription + grants + trial + referral credit into a single
answer; the active set (newest N tools) is computed from it and
applied through ONE shared filter; the enforcement switch defaults
OFF (owner: build now, enforce from launch), and with it off every
surface behaves exactly as before billing existed.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.billing import entitlements, models as billing_models
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
# Anchor for WRITING rows (subscription windows, tool ages): the
# services stamp grants with the real clock, so present-time
# resolutions run WITHOUT a `now` (the real clock again) and only
# the time-travel assertions pass an explicit future `now`. All
# windows are days wide, so the seconds between anchor and resolve
# never flip an outcome.
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


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    # The signup test exercises the real endpoint, whose account
    # numbers come from a Postgres sequence — stub the counter
    # (established pattern, see test_oauth.py).
    counter = itertools.count(900200)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _make_user(db, email, account_types=(MECHANIC,), **kw):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=kw.pop("account_number", f"TV-X-{uuid.uuid4().hex[:6]}"),
        email=email,
        name="Billing User",
        password_hash="not-a-real-hash",
        account_types=list(account_types),
        **kw,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_tool(db, owner_id, name, created_at):
    tool = inventory_models.Tool(
        id=uuid.uuid4(), owner_id=owner_id, name=name, created_at=created_at
    )
    db.add(tool)
    db.commit()
    return tool


def _make_tools(db, owner_id, count, start=NOW):
    return [
        _make_tool(db, owner_id, f"Tool {i:02d}", start + timedelta(minutes=i))
        for i in range(count)
    ]


def _enforce(db):
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)


# -- resolution ---------------------------------------------------------------


def test_no_sources_resolves_free(db):
    user = _make_user(db, "free@example.com")
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "free"
    assert ent.item_limit == 20
    assert ent.is_paid is False
    assert ent.source == "free"


def test_active_subscription_resolves_paid(db):
    user = _make_user(db, "sub@example.com")
    entitlements.upsert_subscription(
        db, user.id, plan_key="pro", status="active", source="stripe",
        current_period_end=NOW + timedelta(days=10),
    )
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "pro"
    assert ent.item_limit is None
    assert ent.source == "subscription"


def test_canceled_subscription_holds_through_period_then_grace(db):
    user = _make_user(db, "grace@example.com")
    entitlements.upsert_subscription(
        db, user.id, plan_key="pro", status="canceled", source="stripe",
        current_period_end=NOW - timedelta(days=1),
        grace_until=NOW + timedelta(days=19),
    )
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "pro"
    assert ent.source == "subscription_grace"
    # Past the grace window: computed drop to Free.
    later = entitlements.resolve_entitlement(db, user.id, now=NOW + timedelta(days=20))
    assert later.plan_key == "free"


def test_trial_window(db):
    user = _make_user(db, "trial@example.com")
    entitlements.upsert_subscription(
        db, user.id, plan_key="pro", status="trialing", source="admin",
        trial_end=NOW + timedelta(days=14),
    )
    ent = entitlements.resolve_entitlement(db, user.id)
    assert (ent.plan_key, ent.source) == ("pro", "trial")
    after = entitlements.resolve_entitlement(db, user.id, now=NOW + timedelta(days=15))
    assert after.plan_key == "free"


def test_grants_stack(db):
    user = _make_user(db, "stack@example.com")
    first = entitlements.grant_period(
        db, user.id, plan_key="pro", kind="free_period", source="redeem_code",
        source_ref="CODE-A", months=1,
    )
    second = entitlements.grant_period(
        db, user.id, plan_key="pro", kind="free_period", source="redeem_code",
        source_ref="CODE-B", months=1,
    )
    # Two one-month grants redeemed back to back = two months total.
    assert second.starts_at == first.ends_at
    assert second.ends_at == entitlements.add_months(first.ends_at, 1)
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "pro"
    assert ent.source == "redeem_code"


def test_expired_grant_is_ignored(db):
    user = _make_user(db, "expired@example.com")
    entitlements.create_grant(
        db, user.id, plan_key="pro", kind="free_period", source="admin",
        starts_at=NOW - timedelta(days=40), ends_at=NOW - timedelta(days=10),
    )
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "free"


def test_lifetime_beats_expiring_subscription(db):
    user = _make_user(db, "life@example.com")
    entitlements.upsert_subscription(
        db, user.id, plan_key="pro", status="active",
        current_period_end=NOW + timedelta(days=3),
    )
    entitlements.create_grant(
        db, user.id, plan_key="business", kind="lifetime", source="redeem_code",
    )
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "business"
    assert ent.source == "lifetime"


def test_business_brackets(db):
    assert entitlements.bracket_for_employee_count(db, 1).bracket_key == "up_to_5"
    assert entitlements.bracket_for_employee_count(db, 5).bracket_key == "up_to_5"
    assert entitlements.bracket_for_employee_count(db, 6).bracket_key == "up_to_10"
    assert entitlements.bracket_for_employee_count(db, 40).bracket_key == "unlimited"


# -- the active set -----------------------------------------------------------


def test_enforcement_off_means_unrestricted(db):
    user = _make_user(db, "off@example.com")
    _make_tools(db, user.id, 25)
    assert entitlements.enforcement_enabled(db) is False
    assert entitlements.active_tool_ids(db, user.id) is None
    assert entitlements.can_add_tool(db, user.id) is True


def test_active_set_is_newest_twenty(db):
    user = _make_user(db, "over@example.com")
    tools = _make_tools(db, user.id, 25)
    _enforce(db)
    active = entitlements.active_tool_ids(db, user.id)
    assert active == {t.id for t in tools[5:]}  # newest 20 of 25
    assert entitlements.can_add_tool(db, user.id) is False


def test_active_set_none_when_within_limit_or_unlimited(db):
    user = _make_user(db, "within@example.com")
    _make_tools(db, user.id, 19)
    _enforce(db)
    assert entitlements.active_tool_ids(db, user.id) is None
    assert entitlements.can_add_tool(db, user.id) is True
    # AT the limit: nothing is inactive yet, but #21 is refused.
    _make_tools(db, user.id, 1, start=NOW + timedelta(hours=1))
    assert entitlements.active_tool_ids(db, user.id) is None
    assert entitlements.can_add_tool(db, user.id) is False
    # An unlimited plan lifts both answers.
    entitlements.create_grant(db, user.id, plan_key="pro", kind="lifetime")
    assert entitlements.active_tool_ids(db, user.id) is None
    assert entitlements.can_add_tool(db, user.id) is True


def test_api_list_flags_inactive_and_stats_exclude(db, client):
    user = _make_user(db, "api@example.com")
    _make_tools(db, user.id, 25)
    _enforce(db)
    headers = auth_headers(user)

    listed = client.get("/api/inventory", headers=headers)
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 25  # the owner's list SHOWS inactive tools
    assert sum(1 for t in body if t["active"]) == 20
    assert sum(1 for t in body if not t["active"]) == 5

    stats = client.get("/api/inventory/stats", headers=headers).json()
    assert stats["total_items"] == 20  # stats EXCLUDE inactive tools

    blocked = client.post(
        "/api/inventory", json={"name": "One too many"}, headers=headers
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "item_limit_reached"


def test_api_enforcement_off_is_byte_identical(db, client):
    user = _make_user(db, "plain@example.com")
    _make_tools(db, user.id, 25)
    headers = auth_headers(user)
    body = client.get("/api/inventory", headers=headers).json()
    assert all(t["active"] is True for t in body)
    stats = client.get("/api/inventory/stats", headers=headers).json()
    assert stats["total_items"] == 25
    created = client.post(
        "/api/inventory", json={"name": "Fine"}, headers=headers
    )
    assert created.status_code == 201


def test_inactive_tools_vanish_from_sharing_surfaces(db):
    """The sweep pin: ONE shared filter — with enforcement on, the
    same 5 oldest tools disappear from the peer list, peer search,
    and the tier-sharing preview, while the owner's own list (the
    API test above) still shows all 25."""
    from app.modules.core import peer_sharing, sharing

    owner = _make_user(db, "sharer@example.com")
    viewer = _make_user(db, "watcher@example.com")
    tools = _make_tools(db, owner.id, 25)
    oldest_names = {t.name for t in tools[:5]}
    db.add(
        core_models.PeerShare(
            owner_id=owner.id, viewer_user_id=viewer.id, status="accepted"
        )
    )
    db.add(
        core_models.ShareConfig(
            owner_id=owner.id, recipient_group="shop_company",
            enabled=True, fields=[],
        )
    )
    for tool in tools:
        db.add(
            core_models.SharedItem(
                owner_id=owner.id, tool_id=tool.id,
                recipient_group="shop_company",
            )
        )
    db.commit()

    # Enforcement OFF: every surface shows everything (unchanged).
    assert len(peer_sharing.list_for_viewer(db, viewer, owner.id)["items"]) == 25
    assert len(peer_sharing.search_for_viewer(db, viewer, "Tool")) == 25
    assert len(sharing.build_preview(db, owner.id, "shop_company")) == 25

    _enforce(db)
    peer_items = peer_sharing.list_for_viewer(db, viewer, owner.id)["items"]
    assert len(peer_items) == 20
    assert not ({i["name"] for i in peer_items} & oldest_names)
    assert len(peer_sharing.search_for_viewer(db, viewer, "Tool")) == 20
    preview = sharing.build_preview(db, owner.id, "shop_company")
    assert len(preview) == 20
    assert not ({p["name"] for p in preview} & oldest_names)


# -- lapse machinery ------------------------------------------------------------


def test_lapse_transitions_flip_ended(db):
    user = _make_user(db, "lapse@example.com")
    sub = entitlements.upsert_subscription(
        db, user.id, plan_key="pro", status="canceled",
        current_period_end=NOW - timedelta(days=30),
        grace_until=NOW - timedelta(days=10),
    )
    assert entitlements.run_lapse_transitions(db, now=NOW) == 1
    db.refresh(sub)
    assert sub.status == "ended"
    # Idempotent: a second run flips nothing.
    assert entitlements.run_lapse_transitions(db, now=NOW) == 0


# -- referrals -------------------------------------------------------------------


def _paying_referral(db, referrer, email):
    fan = _make_user(db, email)
    fan.referred_by_id = referrer.id
    db.commit()
    entitlements.upsert_subscription(
        db, fan.id, plan_key="pro", status="active",
        current_period_end=NOW + timedelta(days=30),
    )
    return fan


def test_referral_rule_five_paying_earns_pro(db):
    referrer = _make_user(db, "referrer@example.com")
    for i in range(4):
        _paying_referral(db, referrer, f"fan{i}@example.com")
    ent = entitlements.resolve_entitlement(db, referrer.id)
    assert ent.referral_paying_count == 4
    assert ent.referral_free_months == 0
    assert ent.plan_key == "free"

    _paying_referral(db, referrer, "fan4@example.com")
    ent = entitlements.resolve_entitlement(db, referrer.id)
    assert ent.referral_paying_count == 5
    assert ent.referral_free_months == 1
    assert ent.plan_key == "pro"
    assert ent.source == "referral"


def test_referral_credit_cannot_bootstrap(db):
    # Middle refers 5 paying users and earns Pro by referral alone.
    # Middle must NOT count as "paying" for Top's rule — referral
    # credit is excluded when evaluating a referred account.
    top = _make_user(db, "top@example.com")
    middle = _make_user(db, "middle@example.com")
    middle.referred_by_id = top.id
    db.commit()
    for i in range(5):
        _paying_referral(db, middle, f"leaf{i}@example.com")
    assert (
        entitlements.resolve_entitlement(db, middle.id).plan_key == "pro"
    )
    ent = entitlements.resolve_entitlement(db, top.id)
    assert ent.referral_paying_count == 0
    assert ent.plan_key == "free"


def test_signup_captures_referral(db, client):
    referrer = _make_user(
        db, "sharer@example.com", account_number="TV-M-000777"
    )
    resp = client.post(
        "/api/core/signup",
        json={
            "name": "New Person",
            "email": "newbie@example.com",
            "password": "hunter2-ok",
            "account_types": [MECHANIC],
            "referral_code": "TV-M-000777",
            "country": "US",
            "currency": "USD",
            "locale": "en",
        },
    )
    assert resp.status_code == 201
    stored = core_service.get_user_by_email(db, "newbie@example.com")
    assert stored.referred_by_id == referrer.id

    # An unknown code never blocks a signup.
    resp = client.post(
        "/api/core/signup",
        json={
            "name": "No Ref",
            "email": "noref@example.com",
            "password": "hunter2-ok",
            "account_types": [MECHANIC],
            "referral_code": "TV-M-999999",
            "country": "US",
            "currency": "USD",
            "locale": "en",
        },
    )
    assert resp.status_code == 201
    assert core_service.get_user_by_email(db, "noref@example.com").referred_by_id is None
