"""Sheet row 107 (2026-11-18): creating an account signs the
person in — signup's answer carries a live session next to
the created user, and that session works. The account number
still rides along as a detail."""

import itertools

import pytest

from app.modules.core import service


@pytest.fixture()
def allocator(monkeypatch):
    """Signup needs Postgres nextval() for the account number;
    like the rest of the suite, stub the allocator."""
    counter = itertools.count(700)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


pytestmark = pytest.mark.usefixtures("allocator")

BASE = {
    "name": "Auto Login",
    "username": "Auto Login",
    "email": "auto-login@example.com",
    "password": "hunter2!",
    "account_types": ["mechanic_technician"],
    "country": "US",
    "currency": "USD",
    "locale": "en",
}


def test_signup_returns_a_working_session(client):
    resp = client.post("/api/core/signup", json=BASE)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["account_number"].startswith("TV-")
    assert body["access_token"]
    assert body["refresh_token"]
    me = client.get(
        "/api/core/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["email"] == BASE["email"]


def test_signup_session_refreshes(client):
    resp = client.post("/api/core/signup", json=BASE)
    assert resp.status_code == 201, resp.text
    refreshed = client.post(
        "/api/core/refresh",
        json={"refresh_token": resp.json()["refresh_token"]},
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"]
