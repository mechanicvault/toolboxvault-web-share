"""Change-password endpoint (Settings → Account & security).

Covers both account kinds the endpoint exists for:
  - OAuth-only accounts (password_login_enabled=False) setting their
    FIRST password with nothing but the live session as proof — after
    which email+password login works.
  - Password accounts changing theirs with the current password —
    wrong/missing current is a 400 and changes nothing.

And the session fallout: a successful change revokes every OTHER
refresh token; the caller's own session survives.

Password length policy is the shared schemas policy (min 6 since the
owner's 2026-10-17 decision): 5 chars rejected here too, 6 accepted.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, hash_opaque_token, hash_password
from app.modules.core import models as core_models, service

CURRENT = "current-password"
SIX = "pw6chr"  # exactly the 6-char policy minimum


def _auth(user: core_models.User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def _password_user(db, account_number: str, email: str) -> core_models.User:
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Password User",
        password_hash=hash_password(CURRENT),
        password_login_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def password_user(db) -> core_models.User:
    return _password_user(db, "TV-000601", "changer@example.com")


@pytest.fixture()
def oauth_user(db, monkeypatch) -> core_models.User:
    monkeypatch.setattr(service, "_next_account_number", lambda _db: "TV-000602")
    return service.create_oauth_user(db, "oauth-only@example.com", "OAuth User")


def _change(client, user, **body):
    return client.post("/api/core/change-password", json=body, headers=_auth(user))


def _login(client, email: str, password: str):
    return client.post("/api/core/login", json={"email": email, "password": password})


def _stored_token(db, plain: str) -> core_models.RefreshToken:
    return db.scalars(
        select(core_models.RefreshToken).where(
            core_models.RefreshToken.token_hash == hash_opaque_token(plain)
        )
    ).first()


# -- the flag itself ---------------------------------------------------------
def test_create_paths_set_the_flag(db, monkeypatch):
    monkeypatch.setattr(service, "_next_account_number", lambda _db: "TV-000603")
    oauth = service.create_oauth_user(db, "flag-oauth@example.com", "O")
    assert oauth.password_login_enabled is False
    monkeypatch.setattr(service, "_next_account_number", lambda _db: "TV-000604")
    # create_user is the email-signup path.
    user = service.create_user(
        db, "flag-email@example.com", "E", "some-password", ["mechanic_technician"]
    )
    assert user.password_login_enabled is True


def test_me_exposes_the_flag(client, password_user, oauth_user):
    me_pw = client.get("/api/core/me", headers=_auth(password_user))
    assert me_pw.status_code == 200
    assert me_pw.json()["password_login_enabled"] is True
    me_oauth = client.get("/api/core/me", headers=_auth(oauth_user))
    assert me_oauth.status_code == 200
    assert me_oauth.json()["password_login_enabled"] is False


# -- OAuth-only: set the first password --------------------------------------
def test_oauth_user_sets_initial_password_then_password_login_works(
    client, db, oauth_user
):
    resp = _change(client, oauth_user, new_password=SIX)
    assert resp.status_code == 204
    db.refresh(oauth_user)
    assert oauth_user.password_login_enabled is True
    login = _login(client, "oauth-only@example.com", SIX)
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_oauth_set_password_still_enforces_min_length(client, oauth_user):
    resp = _change(client, oauth_user, new_password="12345")  # 5 chars
    assert resp.status_code == 422


# -- password accounts: verified change --------------------------------------
def test_change_with_correct_current(client, password_user):
    resp = _change(
        client,
        password_user,
        current_password=CURRENT,
        new_password="brand-new-password",
    )
    assert resp.status_code == 204
    assert _login(client, "changer@example.com", CURRENT).status_code == 401
    assert (
        _login(client, "changer@example.com", "brand-new-password").status_code
        == 200
    )


def test_wrong_current_is_rejected_and_changes_nothing(client, password_user):
    resp = _change(
        client,
        password_user,
        current_password="not-the-password",
        new_password="brand-new-password",
    )
    assert resp.status_code == 400
    assert _login(client, "changer@example.com", CURRENT).status_code == 200
    assert (
        _login(client, "changer@example.com", "brand-new-password").status_code
        == 401
    )


def test_missing_current_is_rejected_for_password_accounts(client, password_user):
    resp = _change(client, password_user, new_password="brand-new-password")
    assert resp.status_code == 400
    assert _login(client, "changer@example.com", CURRENT).status_code == 200


def test_short_new_password_is_rejected(client, password_user):
    resp = _change(
        client, password_user, current_password=CURRENT, new_password="12345"
    )
    assert resp.status_code == 422
    assert _login(client, "changer@example.com", CURRENT).status_code == 200


def test_six_char_new_password_is_accepted(client, password_user):
    resp = _change(client, password_user, current_password=CURRENT, new_password=SIX)
    assert resp.status_code == 204
    assert _login(client, "changer@example.com", SIX).status_code == 200


def test_change_password_requires_auth(client, password_user):
    resp = client.post(
        "/api/core/change-password",
        json={"current_password": CURRENT, "new_password": "brand-new-password"},
    )
    assert resp.status_code == 401


# -- session fallout -----------------------------------------------------------
def test_other_sessions_revoked_current_session_survives(
    client, db, password_user
):
    other_session = service.issue_refresh_token(db, password_user)
    my_session = service.issue_refresh_token(db, password_user)
    resp = _change(
        client,
        password_user,
        current_password=CURRENT,
        new_password="brand-new-password",
        refresh_token=my_session,
    )
    assert resp.status_code == 204
    # The other session's token is revoked on the spot…
    assert _stored_token(db, other_session).revoked_at is not None
    assert _stored_token(db, my_session).revoked_at is None
    # …and behaviorally: mine still rotates, the other is refused.
    mine = client.post("/api/core/refresh", json={"refresh_token": my_session})
    assert mine.status_code == 200
    other = client.post("/api/core/refresh", json={"refresh_token": other_session})
    assert other.status_code == 401
