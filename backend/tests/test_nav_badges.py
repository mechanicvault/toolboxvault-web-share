"""NEW-badge registry (release machinery, owner rule
2026-11-08): the system-settings map behind the nav badges.

The server stores and serves the map; freshness (the first
week) is computed by the client at render. Proves: the shell
endpoint requires a signed-in user and starts empty; the Admin
-> Settings update round-trips the map through the same store
the endpoint reads; a malformed map is refused whole.
"""

import uuid

from app.modules.core import models, nav_badges
from tests.conftest import auth_headers


def _make_user(db, account_number, email, **flags):
    user = models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Test User",
        password_hash="not-a-real-hash",
        **flags,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_registry_endpoint_requires_signin_and_starts_empty(client, user_a):
    assert client.get("/api/core/nav-badges").status_code == 401
    resp = client.get("/api/core/nav-badges", headers=auth_headers(user_a))
    assert resp.status_code == 200
    assert resp.json() == {}


def test_settings_round_trip_through_the_store(client, db, user_a):
    operator = _make_user(db, "TV-000201", "op@example.com", is_operator=True)
    # A normal user cannot write settings at all.
    resp = client.put(
        "/api/admin/settings",
        json={"nav_new_badges": {"reports": "2026-11-08"}},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 403

    resp = client.put(
        "/api/admin/settings",
        json={"nav_new_badges": {"reports": "2026-11-08", "flyers": "2026-11-10"}},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["nav_new_badges"] == {
        "reports": "2026-11-08",
        "flyers": "2026-11-10",
    }
    # The shell endpoint reads the same store.
    resp = client.get("/api/core/nav-badges", headers=auth_headers(user_a))
    assert resp.json() == {"reports": "2026-11-08", "flyers": "2026-11-10"}

    # Clearing is just sending the empty map.
    resp = client.put(
        "/api/admin/settings",
        json={"nav_new_badges": {}},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    assert resp.json()["nav_new_badges"] == {}


def test_malformed_map_is_refused_whole(client, db):
    operator = _make_user(db, "TV-000202", "op2@example.com", is_operator=True)
    headers = auth_headers(operator)
    for bad in (
        {"reports": "08/11/2026"},       # not ISO
        {"reports": "2026-13-40"},       # not a real date
        {"reports": "2026-11-08", "": "2026-11-08"},  # empty key
        {"reports": 20261108},           # not a string
    ):
        resp = client.put(
            "/api/admin/settings", json={"nav_new_badges": bad}, headers=headers
        )
        assert resp.status_code == 422, bad
    # Nothing was stored by the refused writes.
    assert nav_badges.get_nav_badges(db) == {}


def test_badge_map_validation_unit(db):
    assert nav_badges.valid_badge_map({}) is True
    assert nav_badges.valid_badge_map({"a": "2026-02-29"}) is False  # 2026 not a leap year
    assert nav_badges.valid_badge_map({"a": "2028-02-29"}) is True
    assert nav_badges.valid_badge_map(["a"]) is False
    assert nav_badges.valid_badge_map({"a": None}) is False
