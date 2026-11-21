"""Usernames (sheet row 144, owner directive 2026-11-18).

The contract:
- Signup forces a username pick; it must be unique — judged on
  the key form (lowercase, alphanumerics only), so "Tool Box"
  and "Toolbox" are the same name.
- "Toolbox Vault" is reserved: only admin accounts may hold a
  name containing it. The god account's name IS "Toolbox Vault".
- Accounts without a username (pre-existing, social births)
  pick one through POST /me/username; a change is allowed at
  most once every 6 months (admins exempt).
- Other users only ever see the username: the forum's author
  block (the pattern every public surface follows) shows the
  username, never the real name; an unpicked account reads as
  "Member".
"""

import itertools
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.core import models as core_models
from app.modules.core import service, usernames


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    counter = itertools.count(902000)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _signup(client, username, email="new@example.com", name="Real Name"):
    return client.post(
        "/api/core/signup",
        json={
            "email": email,
            "name": name,
            "username": username,
            "password": "secret-1",
            "account_types": ["mechanic_technician"],
        },
    )


def _auth(client, email="new@example.com"):
    resp = client.post(
        "/api/core/login", json={"email": email, "password": "secret-1"}
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_user(db, email, name="Plain Person", username=None, **kw):
    user = service.create_user(
        db,
        email,
        name,
        "secret-1",
        ["mechanic_technician"],
        username=username,
        **kw,
    )
    user.email_verified = True
    db.commit()
    return user


# -- signup -------------------------------------------------------------------


def test_signup_stores_the_username(client, db):
    resp = _signup(client, "Wrench Wizard")
    assert resp.status_code == 201, resp.text
    user = db.query(core_models.User).filter_by(email="new@example.com").one()
    assert user.username == "Wrench Wizard"
    assert user.username_key == "wrenchwizard"
    assert user.username_changed_at is not None


def test_signup_requires_a_username(client, db):
    resp = client.post(
        "/api/core/signup",
        json={
            "email": "nouser@example.com",
            "name": "No Name",
            "password": "secret-1",
            "account_types": ["mechanic_technician"],
        },
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "dupe", ["Wrench Wizard", "wrench wizard", "WRENCHWIZARD", "WrenchWizard"]
)
def test_signup_rejects_a_taken_name_in_any_spelling(client, db, dupe):
    assert _signup(client, "Wrench Wizard").status_code == 201
    resp = _signup(client, dupe, email="second@example.com")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "username_taken"


@pytest.mark.parametrize(
    "reserved", ["Toolbox Vault", "toolboxvault", "The Toolbox Vault Fan"]
)
def test_signup_rejects_the_reserved_name(client, db, reserved):
    resp = _signup(client, reserved)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "username_reserved"


@pytest.mark.parametrize("bad", ["ab", "x" * 25, "!!bad", "a"])
def test_signup_rejects_bad_shapes(client, db, bad):
    resp = _signup(client, bad)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "username_invalid"


# -- the availability check ---------------------------------------------------


def test_username_check_answers(client, db):
    _make_user(db, "taken@example.com", username="Taken Name")
    got = client.get("/api/core/username-check", params={"u": "Free Name"})
    assert got.json() == {"available": True, "reason": None}
    got = client.get("/api/core/username-check", params={"u": "taken name"})
    assert got.json() == {"available": False, "reason": "username_taken"}
    got = client.get("/api/core/username-check", params={"u": "Toolbox Vault"})
    assert got.json() == {"available": False, "reason": "username_reserved"}
    got = client.get("/api/core/username-check", params={"u": "ab"})
    assert got.json() == {"available": False, "reason": "username_invalid"}


# -- the forced pick + the 6-month change rule --------------------------------


def test_unpicked_account_picks_at_sign_in(client, db):
    user = _make_user(db, "old@example.com")  # born before usernames
    assert user.username is None
    headers = _auth(client, "old@example.com")
    me = client.get("/api/core/me", headers=headers)
    assert me.json()["username"] is None
    resp = client.post(
        "/api/core/me/username",
        json={"username": "Old Timer"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "Old Timer"
    assert resp.json()["username_next_change_at"] is not None
    # GET /me serializes the CurrentUser principal, not the ORM
    # row — the unlock date must ride the principal too, or the
    # settings editor never shows the cooldown (rig proof catch,
    # 2026-11-18).
    me = client.get("/api/core/me", headers=headers)
    assert me.json()["username"] == "Old Timer"
    assert me.json()["username_next_change_at"] is not None


def test_change_inside_six_months_is_refused(client, db):
    _make_user(db, "cool@example.com", username="First Pick")
    headers = _auth(client, "cool@example.com")
    resp = client.post(
        "/api/core/me/username",
        json={"username": "Second Pick"},
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "username_cooldown"


def test_change_after_six_months_works(client, db):
    user = _make_user(db, "cool@example.com", username="First Pick")
    user.username_changed_at = datetime.now(timezone.utc) - timedelta(days=200)
    db.commit()
    headers = _auth(client, "cool@example.com")
    resp = client.post(
        "/api/core/me/username",
        json={"username": "Second Pick"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "Second Pick"


def test_admin_may_hold_the_reserved_name_and_skip_cooldown(client, db):
    admin = _make_user(db, "boss@example.com", username="Boss Man")
    admin.is_operator = True
    db.commit()
    headers = _auth(client, "boss@example.com")
    resp = client.post(
        "/api/core/me/username",
        json={"username": "Toolbox Vault"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/api/core/me/username",
        json={"username": "Toolbox Vault Crew"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def test_god_username_constant_is_the_reserved_name():
    assert usernames.GOD_USERNAME == "Toolbox Vault"
    assert usernames.is_reserved_key(usernames.username_key("Toolbox Vault"))


# -- what other users see ------------------------------------------------------


def test_public_name_is_the_username_never_the_real_name(db):
    user = _make_user(db, "pub@example.com", name="Secret Person", username="Public Face")
    assert usernames.public_name(user) == "Public Face"
    unpicked = _make_user(db, "pub2@example.com", name="Hidden Person")
    assert usernames.public_name(unpicked) == "Member"
    assert usernames.public_name(None) == "Former member"


def test_forum_author_block_shows_the_username(client, db):
    from app.modules.forum import service as forum_service

    user = _make_user(db, "auth@example.com", name="Closet Writer", username="Pen Name")
    block = forum_service.author_block(db, user.id)
    assert block["display_name"] == "Pen Name"
