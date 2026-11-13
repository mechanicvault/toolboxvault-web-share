"""Rail pin (widget options Wave 1, owner design 2026-11-02):
whether the left menu rail stays open lives with the ACCOUNT,
like the appearance triple — set once, read at sign-in on
every device.

The API contract under test:
- a fresh account has never set the pin — /me answers null,
  and the client reads null as unpinned (the rail's hover
  behavior, unchanged);
- PATCH /me {rail_pinned: true} pins, {rail_pinned: false}
  unpins, and a later GET /me reads the saved value back;
- a PATCH that doesn't mention the pin leaves it untouched;
- one account's pin never leaks into another's /me.
"""

import itertools

import pytest

from app.modules.billing import models as billing_models
from app.modules.core import service as core_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
PASSWORD = "rail-pin-" + "pass-123"


@pytest.fixture(autouse=True)
def _seed_plans(db):
    db.add(
        billing_models.Plan(
            plan_key="free", name="Free", item_limit=20,
            ai_monthly_credits=0, is_paid=False, sort_order=0,
        )
    )
    db.commit()


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    # service.create_user needs Postgres nextval() for the account
    # number; SQLite has no sequences, so stub the counter (the
    # established pattern — see test_appearance_prefs.py).
    counter = itertools.count(900300)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _signup(db, email, name="Rail Pin User"):
    return core_service.create_user(db, email, name, PASSWORD, [MECHANIC])


def _me(client, user):
    resp = client.get("/api/core/me", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_fresh_account_has_never_set_the_pin(db, client):
    user = _signup(db, "fresh-pin@example.com")
    assert _me(client, user)["rail_pinned"] is None
    row = core_service.get_user_by_id(db, user.id)
    assert row.rail_pinned is None


def test_pin_round_trip(db, client):
    user = _signup(db, "pinned@example.com")
    resp = client.patch(
        "/api/core/me",
        json={"rail_pinned": True},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rail_pinned"] is True
    # A later read — the fresh-login-on-a-new-device case —
    # returns exactly what was saved, from the account row.
    assert _me(client, user)["rail_pinned"] is True
    row = core_service.get_user_by_id(db, user.id)
    assert row.rail_pinned is True

    resp = client.patch(
        "/api/core/me",
        json={"rail_pinned": False},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rail_pinned"] is False
    assert _me(client, user)["rail_pinned"] is False


def test_unrelated_patch_leaves_the_pin_untouched(db, client):
    user = _signup(db, "partial-pin@example.com")
    resp = client.patch(
        "/api/core/me",
        json={"rail_pinned": True},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    resp = client.patch(
        "/api/core/me",
        json={"name": "Renamed User"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    assert _me(client, user)["rail_pinned"] is True


def test_pin_is_owner_scoped(db, client):
    alice = _signup(db, "alice-pin@example.com")
    bob = _signup(db, "bob-pin@example.com")
    resp = client.patch(
        "/api/core/me",
        json={"rail_pinned": True},
        headers=auth_headers(alice),
    )
    assert resp.status_code == 200, resp.text
    assert _me(client, bob)["rail_pinned"] is None
