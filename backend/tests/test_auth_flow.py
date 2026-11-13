"""End-to-end auth flows over HTTP (audits I1, I2, I3): login issues a
token pair, refresh rotates, logout revokes, brute force gets a 429, and
the verification link flips email_verified. SQLite-backed; signup itself
needs Postgres nextval() and is covered at the schema/service level.
"""

import uuid

import pytest

from app.core import notifications
from app.core.security import hash_password
from app.modules.core import models as core_models, service

PASSWORD = "correct-horse-battery"


def _user_with_password(db, account_number: str, email: str) -> core_models.User:
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Flow User",
        password_hash=hash_password(PASSWORD),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def login_user(db) -> core_models.User:
    return _user_with_password(db, "TV-000777", "flow@example.com")


def _login(client, email: str, password: str = PASSWORD):
    return client.post("/api/core/login", json={"email": email, "password": password})


def test_login_returns_a_token_pair(client, login_user):
    response = _login(client, login_user.email)
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_login_wrong_password_is_401(client, login_user):
    response = _login(client, login_user.email, password="wrong-password")
    assert response.status_code == 401


def test_me_with_and_without_token(client, login_user):
    assert client.get("/api/core/me").status_code == 401
    tokens = _login(client, login_user.email).json()
    me = client.get(
        "/api/core/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == login_user.email
    assert me.json()["account_number"] == "TV-000777"


def test_refresh_rotates_and_old_token_dies(client, login_user):
    tokens = _login(client, login_user.email).json()
    refreshed = client.post(
        "/api/core/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    # The rotated-out token must never work again.
    replay = client.post(
        "/api/core/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401


def test_logout_revokes_the_refresh_token(client, login_user):
    tokens = _login(client, login_user.email).json()
    logout = client.post(
        "/api/core/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert logout.status_code == 204
    reuse = client.post(
        "/api/core/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reuse.status_code == 401


def test_login_rate_limit_returns_429(client, db):
    victim = _user_with_password(db, "TV-000888", "victim@example.com")
    for _ in range(5):
        response = _login(client, victim.email, password="wrong-password")
        assert response.status_code == 401
    blocked = _login(client, victim.email, password="wrong-password")
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    # Even the CORRECT password is refused while the window is hot.
    blocked_correct = _login(client, victim.email)
    assert blocked_correct.status_code == 429


def test_verify_email_endpoint(client, db, login_user, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        notifications,
        "send_verification_email",
        lambda db_, email, token, locale="en": captured.update(token=token),
    )
    service.start_email_verification(db, login_user)

    response = client.get(
        "/api/core/verify-email", params={"token": captured["token"]}
    )
    assert response.status_code == 200
    db.refresh(login_user)
    assert login_user.email_verified is True

    again = client.get("/api/core/verify-email", params={"token": captured["token"]})
    assert again.status_code == 400
    bad = client.get("/api/core/verify-email", params={"token": "bogus"})
    assert bad.status_code == 400
