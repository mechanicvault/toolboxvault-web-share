"""Account-held Add-wizard defaults (Wizard Phase 1, 2026-10-25):
the user's wizard setup — pre-checked include sections, usual
location, usual dealer — lives with the ACCOUNT, not the browser.

The API contract under test:
- a fresh account has never saved wizard defaults — /me carries
  wizard_defaults = null, and the client uses the shipped
  behaviour (nothing pre-checked, no usual values);
- PATCH /me saves the document onto the caller's own row, and a
  later GET /me (any device, any browser) reads the same
  document back — including an explicitly bare setup (an empty
  sections list is a real save, not an absence);
- malformed documents (oversized, non-string sections, wrong
  value types) are refused at the schema door with a 422;
- one account's saved defaults never leak into another's /me.
"""

import itertools

import pytest

from app.modules.billing import models as billing_models
from app.modules.core import service as core_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
PASSWORD = "wizard-" + "pass-123"

SAMPLE = {
    "sections": ["warranty", "photos"],
    "location_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
    "dealer_company_id": "",
}


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
    # established pattern — see test_oauth.py).
    counter = itertools.count(900700)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _signup(db, email, name="Wizard User"):
    return core_service.create_user(db, email, name, PASSWORD, [MECHANIC])


def _me(client, user):
    resp = client.get("/api/core/me", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_fresh_account_has_no_saved_wizard_defaults(db, client):
    user = _signup(db, "fresh-wizard@example.com")
    me = _me(client, user)
    assert me["wizard_defaults"] is None


def test_wizard_defaults_save_round_trip(db, client):
    user = _signup(db, "saver-wizard@example.com")
    resp = client.patch(
        "/api/core/me",
        json={"wizard_defaults": SAMPLE},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["wizard_defaults"] == SAMPLE
    # A later read — the fresh-login-on-a-new-device case —
    # returns exactly what was saved, from the account row.
    me = _me(client, user)
    assert me["wizard_defaults"] == SAMPLE
    row = core_service.get_user_by_id(db, user.id)
    assert row.wizard_defaults == SAMPLE


def test_wizard_defaults_bare_setup_is_a_real_save(db, client):
    user = _signup(db, "bare-wizard@example.com")
    bare = {"sections": [], "location_id": "", "dealer_company_id": ""}
    resp = client.patch(
        "/api/core/me",
        json={"wizard_defaults": bare},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    me = _me(client, user)
    # An explicit bare setup round-trips as an object — it is
    # NOT the same as never-saved (null).
    assert me["wizard_defaults"] == bare


def test_wizard_defaults_unrelated_patch_leaves_them_alone(db, client):
    user = _signup(db, "untouched-wizard@example.com")
    resp = client.patch(
        "/api/core/me",
        json={"wizard_defaults": SAMPLE},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    resp = client.patch(
        "/api/core/me",
        json={"name": "Renamed User"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    assert _me(client, user)["wizard_defaults"] == SAMPLE


def test_wizard_defaults_reject_malformed_documents(db, client):
    user = _signup(db, "bad-wizard@example.com")
    bad_payloads = (
        {"sections": "warranty"},                       # not a list
        {"sections": [42]},                             # non-string entry
        {"sections": ["x" * 65]},                       # entry too long
        {"sections": [f"s{i}" for i in range(33)]},     # too many entries
        {"location_id": 42},                            # wrong type
        {"dealer_company_id": "y" * 65},                # too long
        {"blob": "z" * 5000},                           # oversized document
    )
    for doc in bad_payloads:
        resp = client.patch(
            "/api/core/me",
            json={"wizard_defaults": doc},
            headers=auth_headers(user),
        )
        assert resp.status_code == 422, (doc, resp.text)
    # Nothing from the refused writes stuck.
    assert _me(client, user)["wizard_defaults"] is None


def test_wizard_defaults_are_owner_scoped(db, client):
    alice = _signup(db, "alice-wizard@example.com")
    bob = _signup(db, "bob-wizard@example.com")
    resp = client.patch(
        "/api/core/me",
        json={"wizard_defaults": SAMPLE},
        headers=auth_headers(alice),
    )
    assert resp.status_code == 200, resp.text
    assert _me(client, bob)["wizard_defaults"] is None
    assert _me(client, alice)["wizard_defaults"] == SAMPLE
