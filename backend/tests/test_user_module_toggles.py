"""Per-user module on/off (owner 2026-10-24): the user's own
switch layer on top of the operator's module control.

Pins:
- a fresh user has no pref rows and sees the operator baseline;
- flipping a switch hides the module everywhere the gate is
  consulted (my-modules, the module's own routes, the reports it
  feeds, its inbox notifications) and flipping it back restores
  it exactly — hidden notifications keep their unread state;
- a switch can never touch a module the user's groups don't
  entitle, nor an always-on module (inventory / support); an
  unknown id is a 404;
- the dependency cascade: dealers off hides truck accounts with
  blocked_by="dealers" in the prefs list, even though truck
  accounts' own switch is on;
- signup's disabled_modules lands the unchecked modules off,
  ignoring bogus / always-on / unentitled ids without failing;
- the public module-options preview answers without auth.
"""

import itertools
import uuid

import pytest

from app.modules.core import inbox, module_control
from app.modules.core import models as core_models
from app.modules.core import service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"


@pytest.fixture(autouse=True)
def _toggle_tables(db):
    bind = db.get_bind()
    core_models.UserModulePref.__table__.create(bind=bind, checkfirst=True)
    core_models.Notification.__table__.create(bind=bind, checkfirst=True)


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    # Same Postgres-sequence stub as test_signup_basics.py.
    counter = itertools.count(902000)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _make_user(db, account_number, email, account_types):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Toggle User",
        password_hash="not-a-real-hash",
        account_types=account_types,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def mechanic(db):
    return _make_user(db, "TV-M-000301", "toggle-mech@example.com", [MECHANIC])


@pytest.fixture()
def mechanic_dealer(db):
    return _make_user(
        db, "TV-MD-000302", "toggle-md@example.com", [MECHANIC, DEALER]
    )


def _my_module_ids(client, user) -> set[str]:
    resp = client.get("/api/core/my-modules", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return {m["id"] for m in resp.json()}


def _pref(client, user, module_id) -> dict:
    resp = client.get("/api/core/my-module-prefs", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return next(m for m in resp.json() if m["id"] == module_id)


def _put(client, user, module_id, enabled):
    return client.put(
        f"/api/core/my-modules/{module_id}",
        json={"enabled": enabled},
        headers=auth_headers(user),
    )


def _module_unavailable(response, module_id=None) -> bool:
    if response.status_code != 403:
        return False
    detail = response.json()["detail"]
    return detail["code"] == "module_unavailable" and (
        module_id is None or detail["module"] == module_id
    )


# -- (a) fresh-user baseline ---------------------------------------------------


def test_fresh_user_has_no_prefs_and_sees_baseline(client, db, mechanic):
    rows = (
        db.query(core_models.UserModulePref)
        .filter_by(user_id=mechanic.id)
        .all()
    )
    assert rows == []
    baseline = {
        m["id"] for m in module_control.effective_modules(db, [MECHANIC])
    }
    assert _my_module_ids(client, mechanic) == baseline
    assert "borrowing" in baseline

    prefs = client.get(
        "/api/core/my-module-prefs", headers=auth_headers(mechanic)
    ).json()
    assert prefs
    assert all(p["user_enabled"] is True for p in prefs)
    assert all(p["visible"] is True for p in prefs)
    assert all(p["blocked_by"] is None for p in prefs)
    by_id = {p["id"]: p for p in prefs}
    assert by_id["inventory"]["switchable"] is False
    assert by_id["support"]["switchable"] is False
    assert by_id["borrowing"]["switchable"] is True
    assert by_id["borrowing"]["label"] == "Borrowing"
    assert by_id["borrowing"]["nav"]["path"] == "/borrowing"


# -- (b) + (c) off hides, on restores -------------------------------------------


def test_turning_borrowing_off_hides_it_and_on_restores(client, mechanic):
    resp = _put(client, mechanic, "borrowing", False)
    assert resp.status_code == 200, resp.text
    entry = resp.json()
    assert entry["user_enabled"] is False
    assert entry["visible"] is False

    assert "borrowing" not in _my_module_ids(client, mechanic)
    assert _module_unavailable(
        client.get("/api/borrowing/overview", headers=auth_headers(mechanic)),
        "borrowing",
    )
    pref = _pref(client, mechanic, "borrowing")
    assert pref["user_enabled"] is False
    assert pref["visible"] is False

    resp = _put(client, mechanic, "borrowing", True)
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_enabled"] is True
    assert resp.json()["visible"] is True
    assert "borrowing" in _my_module_ids(client, mechanic)
    assert (
        client.get(
            "/api/borrowing/overview", headers=auth_headers(mechanic)
        ).status_code
        == 200
    )


# -- (d) refused flips ------------------------------------------------------------


def test_put_for_unentitled_always_on_and_unknown_modules(client, mechanic):
    # ai_assistant is assigned to no group by default.
    resp = _put(client, mechanic, "ai_assistant", False)
    assert _module_unavailable(resp, "ai_assistant")

    resp = _put(client, mechanic, "inventory", False)
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "module_always_on"
    assert detail["module"] == "inventory"
    # And inventory really is still there.
    assert "inventory" in _my_module_ids(client, mechanic)

    resp = _put(client, mechanic, "nope", False)
    assert resp.status_code == 404


def test_typeless_account_cannot_flip_any_switch(client, db):
    """No account type, no module picking (owner ruling
    2026-11-07): an account that hasn't picked its types has an
    empty prefs read and every PUT is the plain
    module_unavailable refusal — even for a module its future
    groups would entitle. Picking a type unlocks the switches
    immediately, exactly like the module gate everywhere else."""
    user = _make_user(db, "TV-000399", "toggle-none@example.com", [])
    headers = auth_headers(user)
    assert client.get("/api/core/my-module-prefs", headers=headers).json() == []
    assert client.get("/api/core/my-modules", headers=headers).json() == []
    resp = _put(client, user, "borrowing", False)
    assert _module_unavailable(resp, "borrowing")
    rows = (
        db.query(core_models.UserModulePref).filter_by(user_id=user.id).all()
    )
    assert rows == []
    picked = client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=headers,
    )
    assert picked.status_code == 200
    resp = _put(client, user, "borrowing", False)
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_enabled"] is False


# -- (e) dependency cascade --------------------------------------------------------


def test_turning_dealers_off_blocks_truck_accounts(client, mechanic_dealer):
    assert "truck_accounts" in _my_module_ids(client, mechanic_dealer)

    resp = _put(client, mechanic_dealer, "dealers", False)
    assert resp.status_code == 200, resp.text

    pref = _pref(client, mechanic_dealer, "truck_accounts")
    assert pref["user_enabled"] is True  # its own switch never moved
    assert pref["visible"] is False
    assert pref["blocked_by"] == "dealers"
    ids = _my_module_ids(client, mechanic_dealer)
    assert "truck_accounts" not in ids
    assert "dealers" not in ids

    resp = _put(client, mechanic_dealer, "dealers", True)
    assert resp.status_code == 200, resp.text
    pref = _pref(client, mechanic_dealer, "truck_accounts")
    assert pref["visible"] is True
    assert pref["blocked_by"] is None
    assert "truck_accounts" in _my_module_ids(client, mechanic_dealer)


# -- (f) inbox hiding -----------------------------------------------------------------


def test_borrowing_notifications_hide_and_return_unread(client, db, mechanic):
    note = inbox.create_notification(
        db,
        mechanic.id,
        kind=inbox.KIND_BORROW_REQUESTED,
        title="Borrow request",
        body="Pat asked to borrow your Wrench.",
    )
    headers = auth_headers(mechanic)
    inbox_list = client.get("/api/core/notifications", headers=headers).json()
    assert [n["id"] for n in inbox_list] == [str(note.id)]

    assert _put(client, mechanic, "borrowing", False).status_code == 200
    assert client.get("/api/core/notifications", headers=headers).json() == []

    # Mark-all-read must NOT touch the hidden row.
    resp = client.post("/api/core/notifications/read-all", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 0
    db.expire_all()
    row = db.get(core_models.Notification, note.id)
    assert row.read_at is None

    assert _put(client, mechanic, "borrowing", True).status_code == 200
    inbox_list = client.get("/api/core/notifications", headers=headers).json()
    assert [n["id"] for n in inbox_list] == [str(note.id)]
    assert inbox_list[0]["read"] is False


# -- (g) reports gating ------------------------------------------------------------------


def test_checked_out_report_gates_on_borrowing(client, mechanic):
    headers = auth_headers(mechanic)
    resp = client.get("/api/reports/checked-out", headers=headers)
    assert resp.status_code == 200, resp.text

    assert _put(client, mechanic, "borrowing", False).status_code == 200
    resp = client.get("/api/reports/checked-out", headers=headers)
    assert _module_unavailable(resp, "borrowing")

    assert _put(client, mechanic, "borrowing", True).status_code == 200
    resp = client.get("/api/reports/checked-out", headers=headers)
    assert resp.status_code == 200, resp.text


# -- (h) signup choices ---------------------------------------------------------------------


def _signup(client, email, **overrides):
    payload = {
        "email": email,
        "name": "Signup Toggle",
        "password": "secret-1",
        "account_types": [MECHANIC],
        "country": "US",
        "currency": "USD",
        "locale": "en",
        **overrides,
    }
    return client.post("/api/core/signup", json=payload)


def test_signup_with_borrowing_unchecked_starts_with_it_off(client, db):
    resp = _signup(
        client, "toggle-signup@example.com", disabled_modules=["borrowing"]
    )
    assert resp.status_code == 201, resp.text
    user = db.query(core_models.User).filter_by(
        email="toggle-signup@example.com"
    ).one()
    assert "borrowing" not in _my_module_ids(client, user)
    pref = _pref(client, user, "borrowing")
    assert pref["user_enabled"] is False
    assert pref["visible"] is False


def test_signup_with_bogus_and_unentitled_ids_still_succeeds(client, db):
    resp = _signup(
        client,
        "toggle-bogus@example.com",
        disabled_modules=["bogus_module", "ai_assistant", "inventory"],
    )
    assert resp.status_code == 201, resp.text
    user = db.query(core_models.User).filter_by(
        email="toggle-bogus@example.com"
    ).one()
    rows = (
        db.query(core_models.UserModulePref).filter_by(user_id=user.id).all()
    )
    assert rows == []
    assert "inventory" in _my_module_ids(client, user)


# -- (i) public module options ---------------------------------------------------------------


def test_module_options_is_public_and_flags_switchable(client):
    resp = client.get(
        "/api/core/module-options", params={"groups": MECHANIC}
    )
    assert resp.status_code == 200, resp.text
    by_id = {m["id"]: m for m in resp.json()}
    assert "borrowing" in by_id
    assert by_id["borrowing"]["switchable"] is True
    assert "inventory" in by_id
    assert by_id["inventory"]["switchable"] is False
    assert by_id["inventory"]["label"] == "Inventory"

    resp = client.get("/api/core/module-options", params={"groups": "wizard"})
    assert resp.status_code == 422
