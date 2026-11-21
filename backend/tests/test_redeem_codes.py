"""Redeem codes (billing, Phase A1): admin-issued codes redeem into
grants or wallet credits through POST /api/core/redeem, with the
full validation ladder (unknown / deactivated / expired /
exhausted / already-redeemed) and per-user-once enforced by the
ledger. The operator API (create/list/deactivate, grants) is
operator-only — the Phase A2 panel's backend.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.billing import codes, entitlements, models as billing_models
from app.modules.billing import wallet
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
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
    db.commit()


def _make_user(db, email, *, operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-M-{uuid.uuid4().hex[:6]}",
        email=email,
        name="Code User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def operator(db):
    return _make_user(db, "op@example.com", operator=True)


@pytest.fixture()
def user(db):
    return _make_user(db, "redeemer@example.com")


def _redeem(client, user, code):
    return client.post(
        "/api/core/redeem", json={"code": code}, headers=auth_headers(user)
    )


# -- redemption paths -----------------------------------------------------------


def test_redeem_free_months_grants_plan(db, client, user):
    codes.create_code(db, code="FREEMONTH", kind="free_months", amount=1)
    resp = _redeem(client, user, "freemonth")  # case-insensitive
    assert resp.status_code == 200
    assert resp.json()["kind"] == "free_months"
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "pro"
    assert ent.source == "redeem_code"


def test_redeem_free_year_and_lifetime(db, client, user):
    codes.create_code(db, code="YEARONE", kind="free_year")
    codes.create_code(db, code="FOREVER", kind="lifetime", plan_key="business")
    assert _redeem(client, user, "YEARONE").status_code == 200
    assert _redeem(client, user, "FOREVER").status_code == 200
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "business"
    assert ent.source == "lifetime"


def test_redeem_trial_days(db, client, user):
    # Legacy kind (nothing creates it since 2026-10-22) — old rows
    # must keep redeeming.
    codes.create_code(db, code="TRYIT", kind="trial_days", amount=14)
    assert _redeem(client, user, "TRYIT").status_code == 200
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "pro"
    assert ent.source == "trial"


def test_redeem_trial_months(db, client, user):
    codes.create_code(db, code="TRYMONTH", kind="trial_months", amount=3)
    resp = _redeem(client, user, "TRYMONTH")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "trial_months"
    assert resp.json()["message"] == "Code applied — your trial has started."
    ent = entitlements.resolve_entitlement(db, user.id)
    assert ent.plan_key == "pro"
    assert ent.source == "trial"
    grant = db.query(billing_models.EntitlementGrant).filter_by(
        user_id=user.id, kind="trial"
    ).one()
    assert grant.ends_at is not None


def test_redeem_trial_months_month_end_arithmetic(db, client, user, monkeypatch):
    """Jan 31 + 1 calendar month clamps to Feb 28 — the exact
    month-end case subscription periods live by."""
    fixed = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(entitlements, "_now", lambda: fixed)
    codes.create_code(db, code="JAN31", kind="trial_months", amount=1)
    resp = _redeem(client, user, "JAN31")
    assert resp.status_code == 200
    ends_at = datetime.fromisoformat(resp.json()["ends_at"])
    # (SQLite round-trips may drop the tz suffix — compare fields.)
    assert (ends_at.year, ends_at.month, ends_at.day, ends_at.hour) == (
        2026,
        2,
        28,
        12,
    )


def test_admin_create_trial_months_code(db, client, operator, user):
    headers = auth_headers(operator)
    created = client.post(
        "/api/admin/codes",
        json={"code": "TRIAL3", "kind": "trial_months", "amount": 3},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["kind"] == "trial_months"
    # Live instantly, and still not creatable in the legacy kind's
    # place: trial_days remains creatable at the API only because
    # it stays an accepted kind; the panel never offers it.
    assert _redeem(client, user, "TRIAL3").status_code == 200


def test_admin_grant_lifetime_and_months(db, client, operator, user):
    headers = auth_headers(operator)
    lifetime = client.post(
        "/api/admin/grants",
        json={"user_id": str(user.id), "kind": "lifetime"},
        headers=headers,
    )
    assert lifetime.status_code == 201
    assert lifetime.json()["ends_at"] is None
    ent = entitlements.resolve_entitlement(db, user.id)
    assert (ent.plan_key, ent.source) == ("pro", "lifetime")

    no_duration = client.post(
        "/api/admin/grants",
        json={"user_id": str(user.id), "kind": "free_period"},
        headers=headers,
    )
    assert no_duration.status_code == 422


def test_redeem_ai_credits_banks_credits(db, client, user):
    codes.create_code(db, code="CREDITS50", kind="ai_credits", amount=50)
    resp = _redeem(client, user, "CREDITS50")
    assert resp.status_code == 200
    assert resp.json()["credits"] == 50
    view = wallet.wallet_view(db, user.id)
    assert view["banked_balance"] == 50
    assert view["ledger"][0]["reason"] == "redeem"


# -- the validation ladder -------------------------------------------------------


def test_unknown_code(db, client, user):
    resp = _redeem(client, user, "NOSUCHCODE")
    assert resp.status_code == 400
    assert "doesn't look right" in resp.json()["detail"]


def test_double_redeem_refused(db, client, user):
    codes.create_code(db, code="ONCE", kind="free_months", amount=1)
    assert _redeem(client, user, "ONCE").status_code == 200
    resp = _redeem(client, user, "ONCE")
    assert resp.status_code == 400
    assert "already redeemed" in resp.json()["detail"]


def test_expired_code_refused(db, client, user):
    codes.create_code(
        db, code="TOOLATE", kind="free_months", amount=1,
        expires_at=NOW - timedelta(days=1),
    )
    resp = _redeem(client, user, "TOOLATE")
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"]


def test_exhausted_code_refused(db, client, user):
    codes.create_code(
        db, code="GONE", kind="free_months", amount=1, max_redemptions=1
    )
    other = _make_user(db, "first@example.com")
    assert _redeem(client, other, "GONE").status_code == 200
    resp = _redeem(client, user, "GONE")
    assert resp.status_code == 400
    assert "fully redeemed" in resp.json()["detail"]


def test_deactivated_code_refused(db, client, user):
    row = codes.create_code(db, code="KILLED", kind="free_months", amount=1)
    codes.deactivate_code(db, row.id)
    resp = _redeem(client, user, "KILLED")
    assert resp.status_code == 400
    assert "no longer active" in resp.json()["detail"]


# -- the operator API -------------------------------------------------------------


def test_admin_api_is_operator_only(db, client, user):
    assert client.get("/api/admin/codes").status_code == 401
    assert (
        client.get("/api/admin/codes", headers=auth_headers(user)).status_code == 403
    )
    assert (
        client.post(
            "/api/admin/codes",
            json={"code": "X", "kind": "free_year"},
            headers=auth_headers(user),
        ).status_code
        == 403
    )


def test_admin_create_list_deactivate_cycle(db, client, operator, user):
    headers = auth_headers(operator)
    created = client.post(
        "/api/admin/codes",
        json={"code": "panelcode", "kind": "free_months", "amount": 3},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["code"] == "PANELCODE"  # normalized uppercase

    listed = client.get("/api/admin/codes", headers=headers).json()
    assert [c["code"] for c in listed] == ["PANELCODE"]
    assert listed[0]["redemptions"] == 0

    # Live instantly: the user can redeem it right away.
    assert _redeem(client, user, "PANELCODE").status_code == 200
    listed = client.get("/api/admin/codes", headers=headers).json()
    assert listed[0]["redemptions"] == 1

    deactivated = client.post(
        f"/api/admin/codes/{created.json()['id']}/deactivate", headers=headers
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["active"] is False


def test_admin_duplicate_code_and_bad_kind_refused(db, client, operator):
    headers = auth_headers(operator)
    payload = {"code": "DUPE", "kind": "free_year"}
    assert client.post("/api/admin/codes", json=payload, headers=headers).status_code == 201
    assert client.post("/api/admin/codes", json=payload, headers=headers).status_code == 422
    assert (
        client.post(
            "/api/admin/codes",
            json={"code": "BAD", "kind": "free_money"},
            headers=headers,
        ).status_code
        == 422
    )


def test_admin_grant_endpoints(db, client, operator, user):
    headers = auth_headers(operator)
    grant = client.post(
        "/api/admin/grants",
        json={"user_id": str(user.id), "kind": "trial", "days": 30},
        headers=headers,
    )
    assert grant.status_code == 201
    ent = entitlements.resolve_entitlement(db, user.id)
    assert (ent.plan_key, ent.source) == ("pro", "trial")

    credits = client.post(
        "/api/admin/ai-grants",
        json={"user_id": str(user.id), "amount": 25},
        headers=headers,
    )
    assert credits.status_code == 201
    assert credits.json()["banked_balance"] == 25
