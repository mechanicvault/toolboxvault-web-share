"""Account-held appearance (owner ruling, 2026-10-25): mode,
accent and theme live with the ACCOUNT, not the browser.

The API contract under test:
- a fresh account has never saved an appearance — all three
  /me fields are null, and the client keeps its defaults
  (dark + orange) for such accounts;
- PATCH /me saves the appearance triple onto the caller's own
  row, and a later GET /me (any device, any browser) reads the
  same values back;
- invalid values (unknown mode, non-hex accent, malformed
  theme id) are refused at the schema door with a 422;
- one account's saved look never leaks into another's /me.
"""

import itertools

import pytest

from app.modules.billing import models as billing_models
from app.modules.core import service as core_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
PASSWORD = "appearance-" + "pass-123"
BLUE = "#2f6bff"  # AccentDots preset, the pilot video's pick.


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
    counter = itertools.count(900200)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _signup(db, email, name="Appearance User"):
    return core_service.create_user(db, email, name, PASSWORD, [MECHANIC])


def _me(client, user):
    resp = client.get("/api/core/me", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_fresh_account_has_no_saved_appearance(db, client):
    user = _signup(db, "fresh-look@example.com")
    me = _me(client, user)
    assert me["appearance_mode"] is None
    assert me["appearance_accent"] is None
    assert me["appearance_accent_light"] is None
    assert me["appearance_theme"] is None


def test_appearance_save_round_trip(db, client):
    user = _signup(db, "light-blue@example.com")
    resp = client.patch(
        "/api/core/me",
        json={
            "appearance_mode": "light",
            "appearance_accent": BLUE,
            "appearance_theme": "railsteel",
        },
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["appearance_mode"] == "light"
    assert body["appearance_accent"] == BLUE
    assert body["appearance_theme"] == "railsteel"
    # A later read — the fresh-login-on-a-new-device case —
    # returns exactly what was saved, from the account row.
    me = _me(client, user)
    assert me["appearance_mode"] == "light"
    assert me["appearance_accent"] == BLUE
    assert me["appearance_theme"] == "railsteel"
    row = core_service.get_user_by_id(db, user.id)
    assert row.appearance_mode == "light"
    assert row.appearance_accent == BLUE
    assert row.appearance_theme == "railsteel"


def test_appearance_partial_update_applies_only_sent_fields(db, client):
    user = _signup(db, "partial-look@example.com")
    resp = client.patch(
        "/api/core/me",
        json={"appearance_mode": "light"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    me = _me(client, user)
    assert me["appearance_mode"] == "light"
    assert me["appearance_accent"] is None
    assert me["appearance_theme"] is None


def test_appearance_rejects_invalid_values(db, client):
    user = _signup(db, "bad-look@example.com")
    for payload in (
        {"appearance_mode": "purple"},
        {"appearance_accent": "blue"},
        {"appearance_accent": "#12345"},
        {"appearance_accent": "#2f6bff00"},
        {"appearance_theme": "Bad Theme!"},
        {"appearance_theme": ""},
    ):
        resp = client.patch(
            "/api/core/me", json=payload, headers=auth_headers(user)
        )
        assert resp.status_code == 422, (payload, resp.text)
    # Nothing from the refused writes stuck.
    me = _me(client, user)
    assert me["appearance_mode"] is None
    assert me["appearance_accent"] is None
    assert me["appearance_theme"] is None


PINK = "#f0568b"  # AccentDots preset.
SILVER = "#c7ccd4"  # AccentDots grey (silver family) preset.


def test_light_accent_round_trip_is_independent(db, client):
    """Per-mode accent (owner order, 2026-11-08): the light
    pick saves beside the dark pick, and neither writes the
    other — a dark pick made first survives a later light pick
    byte-for-byte, and vice versa."""
    user = _signup(db, "two-modes@example.com")
    resp = client.patch(
        "/api/core/me",
        json={
            "appearance_mode": "dark",
            "appearance_accent": BLUE,
            "appearance_theme": "railsteel",
        },
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    me = _me(client, user)
    assert me["appearance_accent"] == BLUE
    assert me["appearance_accent_light"] is None

    resp = client.patch(
        "/api/core/me",
        json={"appearance_accent_light": PINK},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["appearance_accent_light"] == PINK
    assert body["appearance_accent"] == BLUE
    me = _me(client, user)
    assert me["appearance_accent"] == BLUE
    assert me["appearance_accent_light"] == PINK
    row = core_service.get_user_by_id(db, user.id)
    assert row.appearance_accent == BLUE
    assert row.appearance_accent_light == PINK


def test_light_accent_rejects_invalid_values(db, client):
    user = _signup(db, "bad-light@example.com")
    for payload in (
        {"appearance_accent_light": "silver"},
        {"appearance_accent_light": "#12345"},
        {"appearance_accent_light": "#c7ccd400"},
    ):
        resp = client.patch(
            "/api/core/me", json=payload, headers=auth_headers(user)
        )
        assert resp.status_code == 422, (payload, resp.text)
    me = _me(client, user)
    assert me["appearance_accent_light"] is None


def test_light_accent_is_owner_scoped(db, client):
    alice = _signup(db, "alice-light@example.com")
    bob = _signup(db, "bob-light@example.com")
    resp = client.patch(
        "/api/core/me",
        json={"appearance_accent_light": SILVER},
        headers=auth_headers(alice),
    )
    assert resp.status_code == 200, resp.text
    assert _me(client, alice)["appearance_accent_light"] == SILVER
    assert _me(client, bob)["appearance_accent_light"] is None


def test_appearance_is_owner_scoped(db, client):
    alice = _signup(db, "alice-look@example.com")
    bob = _signup(db, "bob-look@example.com")
    resp = client.patch(
        "/api/core/me",
        json={
            "appearance_mode": "light",
            "appearance_accent": BLUE,
            "appearance_theme": "railsteel",
        },
        headers=auth_headers(alice),
    )
    assert resp.status_code == 200, resp.text
    me_bob = _me(client, bob)
    assert me_bob["appearance_mode"] is None
    assert me_bob["appearance_accent"] is None
    assert me_bob["appearance_theme"] is None
