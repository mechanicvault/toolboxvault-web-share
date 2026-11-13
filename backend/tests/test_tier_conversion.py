"""Tier conversion (owner orders, 2026-11-10): the doors OUT of
the downloads level for an account born into it.

Proven piece by piece:

  * THE CODE DOOR — a downloads account presenting the gate code
    converts (tier + role shadow move together, in the one
    transaction shape every other grant uses); a wrong code
    refuses with the signup gate's own error shape, moves
    nothing, and never echoes the code; failures are throttled
    per account (five wrong inside the window, the sixth attempt
    is a 429 even with the RIGHT code); every other rung is
    refused cleanly (409 already_full_access, before the code is
    even compared); the conversion is audited
    (user.tier_converted, via=access_code, actor = the user).
  * ONE-WAY — rotating the operator's code afterwards demotes
    nobody, and a converted account calling the door again gets
    the same clean refusal as any full account.
  * FIRST FULL ENTRY — the converted account carries the wizard
    birth marker and NO account types, so its onboarding plan
    shows the account-type step pending and the server-deep gate
    refuses later steps until the pick lands — exactly the
    machinery a code-born account meets. Its Home tip dismissal
    is cleared (other layout entries byte-identical).
  * THE REQUEST DOOR — one request per account, EVER: a second
    POST refuses (409 already_requested) while pending, after
    approval, and — the owner's anti-spam ruling — after DENIAL.
    Filing notifies the god accounts only. The god queue lists
    the request with the account's identity; a moderator admin
    (operator flag, no god rung) is refused; approval runs the
    same conversion (audit via=approval, actor = the god) and
    notifies the requester; denial records decider + date,
    notifies the requester, moves nothing, and the code door
    still converts afterwards.
"""

import itertools
import uuid

import pytest

from app.core.rate_limit import tier_conversion_rate_limiter
from app.modules.billing import entitlements
from app.modules.core import (
    models as core_models,
    onboarding,
    service,
    teaser,
    tiers,
)
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
CODE = "97531"

_counter = itertools.count(7000)


@pytest.fixture(autouse=True)
def _clean_throttle():
    tier_conversion_rate_limiter._failures.clear()
    yield
    tier_conversion_rate_limiter._failures.clear()


def _make_user(db, types, *, tier="normal", operator=False, locale="en"):
    n = next(_counter)
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-T-{n:06d}",
        email=f"convert-{n}-{uuid.uuid4().hex[:8]}@example.com",
        name=f"Convert {n}",
        password_hash="not-a-real-hash",
        account_types=list(types),
        is_operator=operator,
        role=tiers.role_for_tier(tier),
        tier=tier,
        locale=locale,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _rung_user(db, **kwargs):
    """A downloads-level account as signup births it: no account
    types, the wizard birth marker set (service._create_user
    marks EVERY new account fresh — mirrored here directly)."""
    user = _make_user(db, [], tier="downloads", **kwargs)
    onboarding.mark_fresh(db, user)
    return user


def _god(db):
    return _make_user(db, [MECHANIC], tier="god", operator=True)


def _set_code(db):
    entitlements.set_setting(db, teaser.GATE_CODE_KEY, CODE)


def _audit_rows(db, action, user_id):
    return (
        db.query(core_models.AuditLog)
        .filter(
            core_models.AuditLog.action == action,
            core_models.AuditLog.target == str(user_id),
        )
        .all()
    )


def _notifications(db, user_id, kind):
    return (
        db.query(core_models.Notification)
        .filter(
            core_models.Notification.user_id == user_id,
            core_models.Notification.kind == kind,
        )
        .all()
    )


# --------------------------------------------------------------------- #
# The code door
# --------------------------------------------------------------------- #


def test_wrong_code_refuses_and_moves_nothing(client, db):
    _set_code(db)
    user = _rung_user(db)
    resp = client.post(
        "/api/core/convert-with-code",
        json={"code": "00000"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_gate_code"
    assert CODE not in resp.text and "00000" not in resp.text
    db.refresh(user)
    assert tiers.resolved_tier(user) == "downloads"
    assert _audit_rows(db, "user.tier_converted", user.id) == []


def test_right_code_converts_and_audits(client, db):
    _set_code(db)
    user = _rung_user(db)
    resp = client.post(
        "/api/core/convert-with-code",
        json={"code": CODE},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"tier": "normal"}
    db.refresh(user)
    assert user.tier == "normal"
    assert user.role == tiers.role_for_tier("normal")
    assert tiers.resolved_tier(user) == "normal"
    rows = _audit_rows(db, "user.tier_converted", user.id)
    assert len(rows) == 1
    assert rows[0].detail["via"] == "access_code"
    assert rows[0].detail["previous"] == "downloads"
    assert rows[0].actor_user_id == user.id


def test_code_attempts_throttle_per_account(client, db):
    _set_code(db)
    user = _rung_user(db)
    headers = auth_headers(user)
    for _ in range(5):
        resp = client.post(
            "/api/core/convert-with-code",
            json={"code": "00000"},
            headers=headers,
        )
        assert resp.status_code == 403, resp.text
    # The sixth attempt is refused BEFORE the code is compared —
    # even the right code waits out the window.
    resp = client.post(
        "/api/core/convert-with-code",
        json={"code": CODE},
        headers=headers,
    )
    assert resp.status_code == 429, resp.text
    assert int(resp.headers["Retry-After"]) > 0
    db.refresh(user)
    assert tiers.resolved_tier(user) == "downloads"
    # Another account's door is untouched by this account's
    # failures (the budget keys per account, not per door).
    other = _rung_user(db)
    resp = client.post(
        "/api/core/convert-with-code",
        json={"code": CODE},
        headers=auth_headers(other),
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("tier", ["normal", "moderator"])
def test_non_rung_callers_refused_cleanly(client, db, tier):
    _set_code(db)
    user = _make_user(db, [MECHANIC], tier=tier)
    resp = client.post(
        "/api/core/convert-with-code",
        json={"code": CODE},
        headers=auth_headers(user),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "already_full_access"
    db.refresh(user)
    assert user.tier == tier


def test_conversion_is_one_way(client, db):
    _set_code(db)
    user = _rung_user(db)
    headers = auth_headers(user)
    resp = client.post(
        "/api/core/convert-with-code", json={"code": CODE}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    # The operator rotates the code; the converted account does
    # not move (nothing reads the code against existing tiers).
    entitlements.set_setting(db, teaser.GATE_CODE_KEY, "13579")
    db.refresh(user)
    assert tiers.resolved_tier(user) == "normal"
    # And the door itself now answers like any full account's.
    resp = client.post(
        "/api/core/convert-with-code", json={"code": "13579"}, headers=headers
    )
    assert resp.status_code == 409, resp.text


def test_convert_requires_auth(client, db):
    resp = client.post("/api/core/convert-with-code", json={"code": CODE})
    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------- #
# First full entry + the tip reset
# --------------------------------------------------------------------- #


def test_first_entry_gate_and_tip_reset(client, db):
    _set_code(db)
    user = _rung_user(db)
    headers = auth_headers(user)
    # The rung Home's layout: the stats box plus a DISMISSED tip.
    service.save_page_layout(
        db,
        user.id,
        "home",
        [
            {"key": "overview", "visible": True},
            {"key": "home_tip", "visible": False},
        ],
    )
    resp = client.post(
        "/api/core/convert-with-code", json={"code": CODE}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    # The tip dismissal is gone; every other entry is untouched.
    layout = service.get_page_layout(db, user.id, "home")
    assert layout == [{"key": "overview", "visible": True}]
    # The account-type gate presents through the existing plan:
    # wizard flow, account-type step pending, and the
    # server-deep gate refuses a later step until the pick.
    plan = client.get("/api/core/onboarding", headers=headers)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["flow"] == "wizard"
    account_type = next(
        s for s in body["steps"] if s["kind"] == "account_type"
    )
    assert account_type["status"] == "pending"
    refused = client.post(
        "/api/core/onboarding/progress",
        json={"step_key": "module:inventory", "status": "done"},
        headers=headers,
    )
    assert refused.status_code == 422, refused.text
    assert "account type" in refused.json()["detail"]


# --------------------------------------------------------------------- #
# The request door
# --------------------------------------------------------------------- #


def test_request_files_once_and_notifies_god(client, db):
    user = _rung_user(db)
    god = _god(db)
    # A moderator admin as the ladder really seats one: the
    # rung WITHOUT the operator flag (the flag derives god —
    # core/tiers.derive_tier — so flag + rung would BE a god
    # account, not a moderator admin).
    moderator_admin = _make_user(db, [MECHANIC], tier="moderator_admin")
    headers = auth_headers(user)
    state = client.get("/api/core/conversion-request", headers=headers)
    assert state.status_code == 200, state.text
    assert state.json()["status"] is None
    resp = client.post("/api/core/conversion-request", headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "pending"
    assert resp.json()["requested_at"] is not None
    # God heard about it; the moderator admin did NOT (god-only
    # machinery, in notifications as in decisions).
    assert len(_notifications(db, god.id, "conversion_requested")) == 1
    assert _notifications(db, moderator_admin.id, "conversion_requested") == []
    # One per account, ever — the second ask refuses.
    again = client.post("/api/core/conversion-request", headers=headers)
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "already_requested"


def test_request_refused_for_full_accounts(client, db):
    user = _make_user(db, [MECHANIC], tier="normal")
    resp = client.post(
        "/api/core/conversion-request", headers=auth_headers(user)
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "already_full_access"


def _file_request(client, user):
    resp = client.post(
        "/api/core/conversion-request", headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp


def _request_id(db, user):
    row = (
        db.query(core_models.ConversionRequest)
        .filter(core_models.ConversionRequest.user_id == user.id)
        .one()
    )
    return row.id


def test_god_queue_and_approval_converts(client, db):
    user = _rung_user(db)
    god = _god(db)
    # A moderator admin as the ladder really seats one: the
    # rung WITHOUT the operator flag (the flag derives god —
    # core/tiers.derive_tier — so flag + rung would BE a god
    # account, not a moderator admin).
    moderator_admin = _make_user(db, [MECHANIC], tier="moderator_admin")
    _file_request(client, user)
    request_id = _request_id(db, user)
    # The queue is god-only: a moderator admin (operator flag
    # held) is refused, as is a plain account.
    queue = client.get(
        "/api/admin/conversion-requests", headers=auth_headers(god)
    )
    assert queue.status_code == 200, queue.text
    rows = queue.json()
    assert len(rows) == 1
    assert rows[0]["id"] == str(request_id)
    assert rows[0]["email"] == user.email
    assert rows[0]["account_number"] == user.account_number
    assert rows[0]["status"] == "pending"
    refused = client.get(
        "/api/admin/conversion-requests",
        headers=auth_headers(moderator_admin),
    )
    assert refused.status_code == 403, refused.text
    refused = client.post(
        f"/api/admin/conversion-requests/{request_id}/approve",
        headers=auth_headers(moderator_admin),
    )
    assert refused.status_code == 403, refused.text
    # Approval converts through the same machinery as the code.
    resp = client.post(
        f"/api/admin/conversion-requests/{request_id}/approve",
        headers=auth_headers(god),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["decided_by_email"] == god.email
    db.refresh(user)
    assert tiers.resolved_tier(user) == "normal"
    audit_rows = _audit_rows(db, "user.tier_converted", user.id)
    assert len(audit_rows) == 1
    assert audit_rows[0].detail["via"] == "approval"
    assert audit_rows[0].actor_user_id == god.id
    assert len(_notifications(db, user.id, "conversion_approved")) == 1
    # A decided request cannot be decided again.
    again = client.post(
        f"/api/admin/conversion-requests/{request_id}/deny",
        headers=auth_headers(god),
    )
    assert again.status_code == 409, again.text


def test_denial_is_final_and_code_door_stays_open(client, db):
    _set_code(db)
    user = _rung_user(db)
    god = _god(db)
    headers = auth_headers(user)
    _file_request(client, user)
    request_id = _request_id(db, user)
    resp = client.post(
        f"/api/admin/conversion-requests/{request_id}/deny",
        headers=auth_headers(god),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "denied"
    assert body["decided_by_email"] == god.email
    assert body["decided_at"] is not None
    db.refresh(user)
    assert tiers.resolved_tier(user) == "downloads"
    assert len(_notifications(db, user.id, "conversion_denied")) == 1
    assert len(_audit_rows(db, "user.conversion_request_denied", user.id)) == 1
    # State reads back as denied…
    state = client.get("/api/core/conversion-request", headers=headers)
    assert state.json()["status"] == "denied"
    # …and the one-ever rule holds AFTER a denial: no second ask.
    again = client.post("/api/core/conversion-request", headers=headers)
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "already_requested"
    # The code door remains the route — and it works.
    resp = client.post(
        "/api/core/convert-with-code", json={"code": CODE}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    db.refresh(user)
    assert tiers.resolved_tier(user) == "normal"


def test_spanish_requester_gets_spanish_decision_copy(client, db):
    user = _rung_user(db, locale="es")
    god = _god(db)
    _file_request(client, user)
    request_id = _request_id(db, user)
    client.post(
        f"/api/admin/conversion-requests/{request_id}/approve",
        headers=auth_headers(god),
    )
    notes = _notifications(db, user.id, "conversion_approved")
    assert len(notes) == 1
    assert notes[0].title == "Bienvenido a la bóveda completa"
