"""Admin panel expansion (Phase A2, owner doctrine 2026-10-18).

Pins, per section:
- Users: operator gating (401 anon / 403 non-operator), directory
  search + pagination, the detail read (entitlement via the
  resolver, wallet, sessions, referrals), every operator action
  (operator grant/revoke, trial, free period, AI credits, role,
  deactivation), and the self-guards (no self-revoke, no
  self-deactivate, no self-ban).
- Promos: a code created through the admin API is redeemable
  IMMEDIATELY (pure DB, no deploy) and shows in the redemptions
  list; deactivation stops redemption.
- Bans: signup blocked, login blocked with clear copy, sessions
  revoked, the OAuth resolve path refuses too, unban restores.
- Settings: defaults, the enforcement switch actually flips the
  engine's answer, AI config round-trips, stats present.
- Audit: module toggles, code create/deactivate, grants, bans,
  role changes, deactivation, and setting changes all leave rows;
  the audit read filters by actor/action and is operator-only.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import hash_password
from app.modules.billing import entitlements, models as billing_models
from app.modules.billing import wallet as wallet_service
from app.modules.core import models as core_models
from app.modules.core import service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    # service.create_user needs Postgres nextval() for the account
    # number; SQLite has no sequences, so stub the counter (the
    # established pattern — see test_account_settings.py).
    counter = itertools.count(900200)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


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


def _make_user(db, email, *, operator=False, password=None, name="Panel User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-M-{uuid.uuid4().hex[:6].upper()}",
        email=email,
        name=name,
        password_hash=hash_password(password) if password else "not-a-real-hash",
        password_login_enabled=password is not None,
        account_types=[MECHANIC],
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def operator(db):
    _seed_plans(db)
    return _make_user(db, "op@example.com", operator=True)


@pytest.fixture()
def target(db):
    return _make_user(db, "target@example.com", name="Target Person")


def _audit_actions(client, operator, **params):
    resp = client.get("/api/admin/audit", params=params, headers=auth_headers(operator))
    assert resp.status_code == 200
    return resp.json()


# -- users: gating + directory -------------------------------------------------


def test_users_directory_requires_operator(client, operator, target):
    assert client.get("/api/admin/users").status_code == 401
    assert (
        client.get("/api/admin/users", headers=auth_headers(target)).status_code
        == 403
    )
    assert (
        client.get("/api/admin/users", headers=auth_headers(operator)).status_code
        == 200
    )


def test_users_directory_search_and_pagination(db, client, operator, target):
    _make_user(db, "second@example.com", name="Second Person")
    page = client.get(
        "/api/admin/users", headers=auth_headers(operator)
    ).json()
    assert page["total"] == 3
    assert page["items"][0]["email"]  # newest first — shape, not order pinning

    by_email = client.get(
        "/api/admin/users", params={"q": "target@"}, headers=auth_headers(operator)
    ).json()
    assert by_email["total"] == 1
    assert by_email["items"][0]["id"] == str(target.id)
    assert by_email["items"][0]["plan_key"] == "free"

    by_number = client.get(
        "/api/admin/users",
        params={"q": target.account_number},
        headers=auth_headers(operator),
    ).json()
    assert by_number["total"] == 1

    paged = client.get(
        "/api/admin/users",
        params={"limit": 2, "offset": 2},
        headers=auth_headers(operator),
    ).json()
    assert paged["total"] == 3 and len(paged["items"]) == 1


def test_user_detail_carries_entitlement_wallet_sessions_referrals(
    db, client, operator, target
):
    wallet_service.credit(db, target.id, amount=40, bucket="banked", reason="grant", ref="test")
    service.issue_session(db, target)
    referred = _make_user(db, "referred@example.com")
    referred.referred_by_id = target.id
    db.commit()

    detail = client.get(
        f"/api/admin/users/{target.id}", headers=auth_headers(operator)
    ).json()
    assert detail["email"] == "target@example.com"
    assert detail["entitlement"]["plan_key"] == "free"
    assert detail["entitlement"]["source"] == "free"
    assert detail["wallet"] == {"allowance_balance": 0, "banked_balance": 40}
    assert detail["session_count"] == 1
    assert detail["referral_count"] == 1
    assert detail["role"] == "user"
    assert detail["is_active"] is True


def test_user_detail_unknown_user_404(client, operator):
    resp = client.get(
        f"/api/admin/users/{uuid.uuid4()}", headers=auth_headers(operator)
    )
    assert resp.status_code == 404


# -- users: operator actions ------------------------------------------------------


def test_operator_grant_and_revoke_with_audit(db, client, operator, target):
    granted = client.post(
        f"/api/admin/users/{target.id}/operator",
        json={"is_operator": True},
        headers=auth_headers(operator),
    )
    assert granted.status_code == 200 and granted.json()["is_operator"] is True
    # The grant is real: the target can now read the directory.
    assert (
        client.get("/api/admin/users", headers=auth_headers(target)).status_code
        == 200
    )
    revoked = client.post(
        f"/api/admin/users/{target.id}/operator",
        json={"is_operator": False},
        headers=auth_headers(operator),
    )
    assert revoked.json()["is_operator"] is False

    actions = _audit_actions(client, operator, action="user.operator_grant")
    assert actions["total"] == 1
    assert actions["items"][0]["target"] == str(target.id)
    assert actions["items"][0]["actor_email"] == "op@example.com"
    assert _audit_actions(client, operator, action="user.operator_revoke")["total"] == 1


def test_operator_cannot_revoke_own_operator_flag(client, operator):
    resp = client.post(
        f"/api/admin/users/{operator.id}/operator",
        json={"is_operator": False},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 400


def test_trial_start_resolves_and_audits(db, client, operator, target):
    resp = client.post(
        f"/api/admin/users/{target.id}/trial",
        json={"plan_key": "pro", "days": 14},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    entitlement = resp.json()["entitlement"]
    assert entitlement["plan_key"] == "pro"
    assert entitlement["source"] == "trial"
    assert _audit_actions(client, operator, action="user.trial_start")["total"] == 1


def test_free_period_grant_resolves(db, client, operator, target):
    resp = client.post(
        f"/api/admin/users/{target.id}/free-period",
        json={"plan_key": "business", "days": 30},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    assert resp.json()["entitlement"]["plan_key"] == "business"
    assert _audit_actions(client, operator, action="user.free_period")["total"] == 1


def test_trial_start_with_months(db, client, operator, target):
    """Months are the admin duration unit (owner 2026-10-22):
    a 2-month trial lands ~2 calendar months out as a trial."""
    resp = client.post(
        f"/api/admin/users/{target.id}/trial",
        json={"plan_key": "pro", "months": 2},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    entitlement = resp.json()["entitlement"]
    assert entitlement["plan_key"] == "pro"
    assert entitlement["source"] == "trial"
    grant = (
        db.query(billing_models.EntitlementGrant)
        .filter_by(user_id=target.id, kind="trial")
        .one()
    )
    ends = grant.ends_at
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    assert now + timedelta(days=55) < ends < now + timedelta(days=65)
    assert _audit_actions(client, operator, action="user.trial_start")["total"] == 1


def test_trial_without_duration_refused(db, client, operator, target):
    resp = client.post(
        f"/api/admin/users/{target.id}/trial",
        json={"plan_key": "pro"},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 422


def test_free_period_with_months_and_lifetime(db, client, operator, target):
    resp = client.post(
        f"/api/admin/users/{target.id}/free-period",
        json={"plan_key": "pro", "months": 3},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    assert resp.json()["entitlement"]["source"] == "admin"

    other = _make_user(db, "lifetime-target@example.com")
    resp = client.post(
        f"/api/admin/users/{other.id}/free-period",
        json={"plan_key": "pro", "lifetime": True},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    entitlement = resp.json()["entitlement"]
    assert entitlement["plan_key"] == "pro"
    assert entitlement["source"] == "lifetime"
    grant = (
        db.query(billing_models.EntitlementGrant)
        .filter_by(user_id=other.id, kind="lifetime")
        .one()
    )
    assert grant.ends_at is None


def test_ai_credits_grant_lands_in_banked_bucket(db, client, operator, target):
    resp = client.post(
        f"/api/admin/users/{target.id}/ai-credits",
        json={"amount": 250},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    assert resp.json()["wallet"]["banked_balance"] == 250
    view = wallet_service.wallet_view(db, target.id)
    assert view["ledger"][0]["reason"] == "grant"
    assert _audit_actions(client, operator, action="user.ai_credits")["total"] == 1


def test_role_set_and_invalid_role(db, client, operator, target):
    resp = client.post(
        f"/api/admin/users/{target.id}/role",
        json={"role": "moderator"},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200 and resp.json()["role"] == "moderator"
    bad = client.post(
        f"/api/admin/users/{target.id}/role",
        json={"role": "superuser"},
        headers=auth_headers(operator),
    )
    assert bad.status_code == 422
    rows = _audit_actions(client, operator, action="user.role_set")
    assert rows["total"] == 1 and rows["items"][0]["detail"]["role"] == "moderator"


# -- deactivation --------------------------------------------------------------


def _signup_and_login(client, email, password="hunter22"):
    signup = client.post(
        "/api/core/signup",
        json={
            "email": email,
            "name": "Real Person",
            "password": password,
            "account_types": [MECHANIC],
            "country": "US",
            "currency": "USD",
            "locale": "en",
        },
    )
    assert signup.status_code == 201, signup.text
    login = client.post(
        "/api/core/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return signup.json()["id"], login.json()


def test_deactivate_blocks_login_and_kills_sessions(db, client, operator):
    user_id, tokens = _signup_and_login(client, "victim@example.com")

    resp = client.post(
        f"/api/admin/users/{user_id}/deactivate", headers=auth_headers(operator)
    )
    assert resp.status_code == 200 and resp.json()["is_active"] is False

    # Sign-in is refused with plain copy.
    refused = client.post(
        "/api/core/login",
        json={"email": "victim@example.com", "password": "hunter22"},
    )
    assert refused.status_code == 403
    assert "deactivated" in refused.json()["detail"]
    # The live session died with the deactivation.
    refreshed = client.post(
        "/api/core/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 401
    me = client.get(
        "/api/core/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 403

    # Reactivation restores sign-in (data never left).
    client.post(
        f"/api/admin/users/{user_id}/reactivate", headers=auth_headers(operator)
    )
    again = client.post(
        "/api/core/login",
        json={"email": "victim@example.com", "password": "hunter22"},
    )
    assert again.status_code == 200
    assert _audit_actions(client, operator, action="user.deactivate")["total"] == 1
    assert _audit_actions(client, operator, action="user.reactivate")["total"] == 1


def test_operator_cannot_deactivate_self(client, operator):
    resp = client.post(
        f"/api/admin/users/{operator.id}/deactivate",
        headers=auth_headers(operator),
    )
    assert resp.status_code == 400


# -- bans ------------------------------------------------------------------------


def test_ban_blocks_signup_and_unban_restores(db, client, operator):
    created = client.post(
        "/api/admin/bans",
        json={"email": "spam@example.com", "reason": "spam signups"},
        headers=auth_headers(operator),
    )
    assert created.status_code == 201
    assert created.json()["banned_by_email"] == "op@example.com"

    blocked = client.post(
        "/api/core/signup",
        json={
            "email": "spam@example.com",
            "name": "Spam",
            "password": "hunter22",
            "account_types": [MECHANIC],
            "country": "US",
            "currency": "USD",
            "locale": "en",
        },
    )
    assert blocked.status_code == 403

    bans = client.get("/api/admin/bans", headers=auth_headers(operator)).json()
    assert [b["email"] for b in bans] == ["spam@example.com"]
    removed = client.delete(
        f"/api/admin/bans/{created.json()['id']}", headers=auth_headers(operator)
    )
    assert removed.status_code == 204

    allowed = client.post(
        "/api/core/signup",
        json={
            "email": "spam@example.com",
            "name": "Reformed",
            "password": "hunter22",
            "account_types": [MECHANIC],
            "country": "US",
            "currency": "USD",
            "locale": "en",
        },
    )
    assert allowed.status_code == 201
    assert _audit_actions(client, operator, action="ban.create")["total"] == 1
    assert _audit_actions(client, operator, action="ban.remove")["total"] == 1


def test_ban_blocks_login_and_revokes_sessions(db, client, operator):
    user_id, tokens = _signup_and_login(client, "banned-later@example.com")
    client.post(
        "/api/admin/bans",
        json={"email": "banned-later@example.com", "reason": "chargebacks"},
        headers=auth_headers(operator),
    )
    refused = client.post(
        "/api/core/login",
        json={"email": "banned-later@example.com", "password": "hunter22"},
    )
    assert refused.status_code == 403
    assert "blocked" in refused.json()["detail"]
    refreshed = client.post(
        "/api/core/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 401
    me = client.get(
        "/api/core/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 403


def test_ban_blocks_oauth_resolve_and_deactivated_too(db, operator):
    service.ban_email(db, "oauth-spam@example.com", reason="spam", banned_by=operator.id)
    with pytest.raises(service.EmailBannedError):
        service.resolve_oauth_user(db, "oauth-spam@example.com", "Spam")

    user = _make_user(db, "oauth-off@example.com")
    service.set_user_active(db, user, False)
    with pytest.raises(service.AccountDeactivatedError):
        service.resolve_oauth_user(db, "oauth-off@example.com", "Off")


def test_operator_cannot_ban_own_email(client, operator):
    resp = client.post(
        "/api/admin/bans",
        json={"email": "op@example.com", "reason": "oops"},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 400


def test_bans_require_operator(client, target):
    assert client.get("/api/admin/bans").status_code == 401
    assert client.get("/api/admin/bans", headers=auth_headers(target)).status_code == 403


# -- promos --------------------------------------------------------------------


def test_code_created_in_panel_redeems_immediately(db, client, operator, target):
    created = client.post(
        "/api/admin/codes",
        json={"code": "PANEL1", "kind": "free_months", "amount": 1, "plan_key": "pro"},
        headers=auth_headers(operator),
    )
    assert created.status_code == 201

    redeemed = client.post(
        "/api/core/redeem", json={"code": "PANEL1"}, headers=auth_headers(target)
    )
    assert redeemed.status_code == 200
    assert entitlements.resolve_entitlement(db, target.id).plan_key == "pro"

    recent = client.get(
        "/api/admin/redemptions", headers=auth_headers(operator)
    ).json()
    assert len(recent) == 1
    assert recent[0]["code"] == "PANEL1"
    assert recent[0]["user_email"] == "target@example.com"

    codes_list = client.get(
        "/api/admin/codes", headers=auth_headers(operator)
    ).json()
    assert codes_list[0]["redemptions"] == 1
    assert _audit_actions(client, operator, action="code.create")["total"] == 1


def test_code_deactivate_stops_redemption_and_audits(db, client, operator, target):
    created = client.post(
        "/api/admin/codes",
        json={"code": "PANEL2", "kind": "ai_credits", "amount": 10},
        headers=auth_headers(operator),
    ).json()
    client.post(
        f"/api/admin/codes/{created['id']}/deactivate",
        headers=auth_headers(operator),
    )
    refused = client.post(
        "/api/core/redeem", json={"code": "PANEL2"}, headers=auth_headers(target)
    )
    assert refused.status_code == 400
    assert _audit_actions(client, operator, action="code.deactivate")["total"] == 1


def test_billing_grants_write_audit_rows(db, client, operator, target):
    grant = client.post(
        "/api/admin/grants",
        json={
            "user_id": str(target.id),
            "plan_key": "pro",
            "kind": "trial",
            "days": 7,
        },
        headers=auth_headers(operator),
    )
    assert grant.status_code == 201
    ai = client.post(
        "/api/admin/ai-grants",
        json={"user_id": str(target.id), "amount": 5},
        headers=auth_headers(operator),
    )
    assert ai.status_code == 201
    assert _audit_actions(client, operator, action="grant.create")["total"] == 1
    assert _audit_actions(client, operator, action="ai_grant.create")["total"] == 1


# -- settings ---------------------------------------------------------------------


def test_settings_defaults_and_stats(db, client, operator, target):
    view = client.get("/api/admin/settings", headers=auth_headers(operator)).json()
    assert view["enforcement_enabled"] is False
    # Wave 4: the AI block carries the per-action credit prices
    # (all 0 = free until an operator prices them), and the
    # product-lookup block starts fully dark (blank = skipped).
    # 2026-10-25: the block also carries the per-action model
    # overrides (blank = rides the site model).
    assert view["ai"] == {
        "provider": "",
        "model": "",
        "api_key_ref": "",
        "prices": {
            "lookup": 0,
            "identify": 0,
            "manual_lookup": 0,
            "report_summary": 0,
            "drawer_lookup": 0,
        },
        "action_models": {"drawer_lookup": ""},
    }
    # No manual_search_* keys: web search rides the AI seam
    # (owner's one-vendor decision, 2026-10-25) and has no
    # settings of its own to default.
    assert view["lookup"] == {
        "upc_provider": "",
        "upc_api_key_ref": "",
    }
    assert view["stats"]["users"] == 2
    assert view["stats"]["feature_modules"] >= 3
    assert view["stats"]["tables"]["users"] == 2


def test_settings_update_flips_engine_and_roundtrips_ai(db, client, operator, target):
    updated = client.put(
        "/api/admin/settings",
        json={
            "enforcement_enabled": True,
            "ai_provider": "anthropic",
            "ai_model": "claude-sonnet",
            "ai_api_key_ref": "ANTHROPIC_API_KEY",
        },
        headers=auth_headers(operator),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["enforcement_enabled"] is True
    assert body["ai"]["provider"] == "anthropic"
    # The engine itself reads the flipped switch.
    assert entitlements.enforcement_enabled(db) is True
    rows = _audit_actions(client, operator, action="setting.update")
    assert rows["total"] == 4  # one row per changed key


def test_settings_requires_operator(client, target):
    assert client.get("/api/admin/settings").status_code == 401
    assert (
        client.get("/api/admin/settings", headers=auth_headers(target)).status_code
        == 403
    )


# -- audit ------------------------------------------------------------------------


def test_module_toggle_writes_audit(db, client, operator):
    resp = client.put(
        "/api/admin/modules/inventory/global",
        json={"enabled": False},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    rows = _audit_actions(client, operator, action="module.global_toggle")
    assert rows["total"] == 1
    assert rows["items"][0]["target"] == "inventory"
    assert rows["items"][0]["detail"] == {"enabled": False}

    client.put(
        "/api/admin/modules/inventory/groups/shop_company",
        json={"enabled": True},
        headers=auth_headers(operator),
    )
    rows = _audit_actions(client, operator, action="module.group_assignment")
    assert rows["total"] == 1
    assert rows["items"][0]["detail"]["group"] == "shop_company"


def test_audit_filters_by_actor_and_date(db, client, operator, target):
    audit_seed = client.post(
        f"/api/admin/users/{target.id}/role",
        json={"role": "moderator"},
        headers=auth_headers(operator),
    )
    assert audit_seed.status_code == 200
    by_actor = client.get(
        "/api/admin/audit",
        params={"actor": "op@example"},
        headers=auth_headers(operator),
    ).json()
    assert by_actor["total"] >= 1
    none = client.get(
        "/api/admin/audit",
        params={"actor": "nobody@example"},
        headers=auth_headers(operator),
    ).json()
    assert none["total"] == 0
    future = client.get(
        "/api/admin/audit",
        params={"since": "2999-01-01T00:00:00Z"},
        headers=auth_headers(operator),
    ).json()
    assert future["total"] == 0


def test_audit_requires_operator(client, target):
    assert client.get("/api/admin/audit").status_code == 401
    assert client.get("/api/admin/audit", headers=auth_headers(target)).status_code == 403
