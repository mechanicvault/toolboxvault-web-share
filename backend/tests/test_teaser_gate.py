"""Teaser mode + the signup gate (owner order, 2026-10-26;
OPEN SIGNUP, owner order 2026-11-09).

While teaser mode is on, the gate code decides WHAT a new
account is, at BOTH creation doors (email signup and social
find-or-create), never just in the page: WITH the unlock (the
code, traded for the cookie) the account is born normal — the
full site, as the gate always granted; WITHOUT it the account
is born on the downloads level (core/tiers.py), the limited
rung that reaches Downloads + Help and nothing else. Signup
itself is open — no code is needed to create the limited
account, and a wrong code is still an honest refusal at the
unlock endpoint, never a silent downgrade. The code itself
must never appear in any public response. With the switch off,
signup behaves exactly as it did before the teaser existed.
"""

import itertools
import uuid

import pytest
from starlette.requests import Request

from app.core.security import create_signup_unlock_token, hash_password
from app.modules.billing import entitlements
from app.modules.core import models as core_models
from app.modules.core import oauth_routes, service, teaser


@pytest.fixture(autouse=True)
def _allocator(monkeypatch):
    """Stub the account-number sequence (a Postgres sequence in
    production; SQLite tests stub it, like test_account_types)."""
    counter = itertools.count(900)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-M-{next(counter):06d}",
    )

SIGNUP = {
    "email": "gate@example.com",
    "name": "Gate Walker",
    "password": "secret1",
    "account_types": ["mechanic_technician"],
    "country": "US",
    "currency": "USD",
    "locale": "en",
}


def _teaser_on(db):
    entitlements.set_setting(db, teaser.ENABLED_KEY, True)


def _request_with_cookie(token: str | None) -> Request:
    headers = [(b"cookie", f"{teaser.UNLOCK_COOKIE}={token}".encode())] if token else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def _user_count(db) -> int:
    return db.query(core_models.User).count()


# -- default posture ---------------------------------------------------


def test_signup_open_by_default(client, db):
    gate = client.get("/api/core/signup-gate")
    assert gate.status_code == 200
    assert gate.json() == {"teaser_mode": False, "unlocked": False}
    landing = client.get("/api/core/landing")
    assert landing.json()["teaser_mode"] is False
    assert client.post("/api/core/signup", json=SIGNUP).status_code == 201


# -- the locked door ----------------------------------------------------


def test_teaser_on_signup_lands_on_the_downloads_level(client, db):
    _teaser_on(db)
    gate = client.get("/api/core/signup-gate")
    assert gate.json() == {"teaser_mode": True, "unlocked": False}
    before = _user_count(db)
    created = client.post("/api/core/signup", json=SIGNUP)
    assert created.status_code == 201
    # The account exists — on the limited rung, in the response
    # and on the row, resolved and stored alike.
    assert created.json()["tier"] == "downloads"
    assert _user_count(db) == before + 1
    user = service.get_user_by_email(db, SIGNUP["email"])
    assert user is not None
    assert user.tier == "downloads"
    from app.modules.core import tiers as tiers_mod

    assert tiers_mod.resolved_tier(user) == "downloads"


def test_landing_reports_teaser_without_leaking_the_code(client, db):
    _teaser_on(db)
    landing = client.get("/api/core/landing")
    assert landing.json()["teaser_mode"] is True
    assert teaser.DEFAULT_GATE_CODE not in landing.text
    gate = client.get("/api/core/signup-gate")
    assert teaser.DEFAULT_GATE_CODE not in gate.text


def test_unlock_wrong_code_then_right_code(client, db):
    _teaser_on(db)
    wrong = client.post("/api/core/signup-unlock", json={"code": "0000"})
    assert wrong.status_code == 403
    assert wrong.json()["detail"]["code"] == "invalid_gate_code"
    assert teaser.DEFAULT_GATE_CODE not in wrong.text
    # Still un-unlocked after the wrong try — and a signup from
    # this browser lands on the limited level, which is the
    # honest no-code outcome, NOT a punishment for the wrong try.
    assert client.get("/api/core/signup-gate").json()["unlocked"] is False
    limited = client.post("/api/core/signup", json=SIGNUP)
    assert limited.status_code == 201
    assert limited.json()["tier"] == "downloads"

    right = client.post(
        "/api/core/signup-unlock", json={"code": teaser.DEFAULT_GATE_CODE}
    )
    assert right.status_code == 200
    assert right.json() == {"teaser_mode": True, "unlocked": True}
    cookie = right.headers.get("set-cookie", "")
    assert teaser.UNLOCK_COOKIE in cookie and "HttpOnly" in cookie
    # The TestClient keeps the cookie jar: the door now opens end to end.
    assert client.get("/api/core/signup-gate").json()["unlocked"] is True
    full = client.post(
        "/api/core/signup", json={**SIGNUP, "email": "gate-full@example.com"}
    )
    assert full.status_code == 201
    assert full.json()["tier"] == "normal"


def test_unlock_endpoint_when_teaser_off(client, db):
    answer = client.post(
        "/api/core/signup-unlock", json={"code": teaser.DEFAULT_GATE_CODE}
    )
    assert answer.status_code == 200
    assert answer.json() == {"teaser_mode": False, "unlocked": True}
    assert "set-cookie" not in answer.headers


def test_switch_off_restores_open_signup(client, db):
    _teaser_on(db)
    limited = client.post("/api/core/signup", json=SIGNUP)
    assert limited.status_code == 201
    assert limited.json()["tier"] == "downloads"
    entitlements.set_setting(db, teaser.ENABLED_KEY, False)
    assert client.get("/api/core/landing").json()["teaser_mode"] is False
    full = client.post(
        "/api/core/signup", json={**SIGNUP, "email": "gate-off@example.com"}
    )
    assert full.status_code == 201
    assert full.json()["tier"] == "normal"


# -- the social door ------------------------------------------------------


def test_oauth_new_account_lands_on_downloads_but_signin_passes(client, db):
    _teaser_on(db)
    identity = {"email": "social@example.com", "name": "Social Walker"}
    # A brand-new social identity without the unlock: the account
    # IS created (a social signup is a signup) — on the limited
    # level, like an email signup from the same browser.
    created = oauth_routes._finish(db, identity, request=_request_with_cookie(None))
    assert created.status_code == 302
    assert "/auth/callback" in created.headers["location"]
    user = service.get_user_by_email(db, identity["email"])
    assert user is not None and user.tier == "downloads"
    # A new identity WITH the unlock: born normal, the full site.
    identity2 = {"email": "social-full@example.com", "name": "Social Full"}
    allowed = oauth_routes._finish(
        db,
        identity2,
        request=_request_with_cookie(create_signup_unlock_token()),
    )
    assert "/auth/callback" in allowed.headers["location"]
    user2 = service.get_user_by_email(db, identity2["email"])
    assert user2 is not None and user2.tier == "normal"
    # And once an account exists, social sign-in needs no unlock
    # and never moves its rung.
    again = oauth_routes._finish(db, identity, request=_request_with_cookie(None))
    assert "/auth/callback" in again.headers["location"]
    assert service.get_user_by_email(db, identity["email"]).tier == "downloads"


# -- operator controls ----------------------------------------------------


def _operator(db):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000001",
        email="teaser-op@example.com",
        name="Teaser Op",
        password_hash=hash_password("operator-password"),
        password_login_enabled=True,
        account_types=["mechanic_technician"],
        is_operator=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_admin_settings_flip_switch_and_set_custom_code(client, db):
    from tests.conftest import auth_headers

    op = _operator(db)
    headers = auth_headers(op)
    view = client.get("/api/admin/settings", headers=headers)
    assert view.json()["teaser"] == {
        "enabled": False,
        "gate_code_custom": False,
        "video_set": False,
        "video_name": "",
    }

    saved = client.put(
        "/api/admin/settings",
        headers=headers,
        json={"teaser_enabled": True, "teaser_gate_code": "97531"},
    )
    assert saved.status_code == 200
    assert saved.json()["teaser"] == {
        "enabled": True,
        "gate_code_custom": True,
        "video_set": False,
        "video_name": "",
    }
    # The code itself is never echoed back, anywhere in the view.
    assert "97531" not in saved.text
    # The default code is dead; the custom code opens the door.
    assert (
        client.post("/api/core/signup-unlock", json={"code": "4823"}).status_code
        == 403
    )
    assert (
        client.post("/api/core/signup-unlock", json={"code": "97531"}).status_code
        == 200
    )


def test_admin_settings_refuses_a_too_short_code(client, db):
    from tests.conftest import auth_headers

    op = _operator(db)
    refused = client.put(
        "/api/admin/settings",
        headers=auth_headers(op),
        json={"teaser_gate_code": "abc"},
    )
    assert refused.status_code == 422
    assert teaser.gate_code(db) == teaser.DEFAULT_GATE_CODE


# -- the teaser video slot ------------------------------------------------


def _fake_storage(monkeypatch, *, content_type="video/mp4", magic=b"ftyp"):
    """Stub the storage singleton the way the codebase's other
    upload tests do: presigns are fake URLs, HEAD reports the
    given type, the prefix read carries (or omits) the MP4 magic,
    deletes are recorded."""
    from app.core import storage as storage_module
    from app.core.storage import StoredObject

    deleted: list[str] = []
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_put_url",
        lambda key, ct, expires_in=900: f"https://storage.invalid/put/{key}",
    )
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_get_url",
        lambda key, expires_in=3600: f"https://storage.invalid/get/{key}",
    )
    monkeypatch.setattr(
        storage_module.storage,
        "head",
        lambda key: StoredObject(
            key=key,
            size_bytes=1024,
            content_type=(
                content_type if key.startswith(teaser.VIDEO_KEY_PREFIX)
                else "image/webp"
            ),
        ),
    )
    monkeypatch.setattr(
        storage_module.storage,
        "fetch_prefix",
        lambda key, length=512: b"\x00\x00\x00\x18" + magic + b"isom",
    )
    monkeypatch.setattr(storage_module.storage, "delete", deleted.append)
    return deleted


def _set_video_via_api(client, headers, name="teaser-one.mp4"):
    url = client.post(
        "/api/admin/settings/teaser-video/upload-url",
        headers=headers,
        json={
            "kind": "video",
            "filename": name,
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    )
    assert url.status_code == 200, url.text
    key = url.json()["key"]
    done = client.post(
        "/api/admin/settings/teaser-video/complete",
        headers=headers,
        json={"key": key, "poster_key": "", "name": name},
    )
    assert done.status_code == 200, done.text
    return key, done


def test_teaser_video_upload_url_validation(client, db, monkeypatch):
    from tests.conftest import auth_headers

    _fake_storage(monkeypatch)
    headers = auth_headers(_operator(db))
    # Not an MP4 → refused before any URL is minted.
    refused = client.post(
        "/api/admin/settings/teaser-video/upload-url",
        headers=headers,
        json={
            "kind": "video",
            "filename": "clip.mov",
            "content_type": "video/quicktime",
            "size_bytes": 1024,
        },
    )
    assert refused.status_code == 422
    # Over the series' 10 MiB cap → refused.
    oversize = client.post(
        "/api/admin/settings/teaser-video/upload-url",
        headers=headers,
        json={
            "kind": "video",
            "filename": "big.mp4",
            "content_type": "video/mp4",
            "size_bytes": teaser.VIDEO_MAX_BYTES + 1,
        },
    )
    assert oversize.status_code == 422
    # A good ask mints a key under the teaser namespace.
    ok = client.post(
        "/api/admin/settings/teaser-video/upload-url",
        headers=headers,
        json={
            "kind": "video",
            "filename": "teaser-one.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["key"].startswith(teaser.VIDEO_KEY_PREFIX)
    # Signed-out callers get nothing.
    assert (
        client.post(
            "/api/admin/settings/teaser-video/upload-url",
            json={
                "kind": "video",
                "filename": "x.mp4",
                "content_type": "video/mp4",
                "size_bytes": 1,
            },
        ).status_code
        in (401, 403)
    )


def test_teaser_video_set_replace_clear_and_landing_urls(client, db, monkeypatch):
    from tests.conftest import auth_headers

    deleted = _fake_storage(monkeypatch)
    headers = auth_headers(_operator(db))
    _teaser_on(db)
    # Empty slot: the landing carries no video trace.
    landing = client.get("/api/core/landing").json()
    assert landing["teaser_video_url"] == "" and landing["teaser_poster_url"] == ""

    key_one, done = _set_video_via_api(client, headers)
    assert done.json()["teaser"]["video_set"] is True
    assert done.json()["teaser"]["video_name"] == "teaser-one.mp4"
    landing = client.get("/api/core/landing").json()
    assert landing["teaser_video_url"] == f"https://storage.invalid/get/{key_one}"

    # Replace: the settings move and the OLD object is deleted.
    key_two, done = _set_video_via_api(client, headers, name="teaser-two.mp4")
    assert done.json()["teaser"]["video_name"] == "teaser-two.mp4"
    assert key_one in deleted
    landing = client.get("/api/core/landing").json()
    assert landing["teaser_video_url"] == f"https://storage.invalid/get/{key_two}"

    # Teaser OFF: the landing must not carry the video at all —
    # switch-off means the pre-teaser build, exactly.
    entitlements.set_setting(db, teaser.ENABLED_KEY, False)
    landing = client.get("/api/core/landing").json()
    assert landing["teaser_video_url"] == "" and landing["teaser_poster_url"] == ""
    entitlements.set_setting(db, teaser.ENABLED_KEY, True)

    # Clear: slot empties, the object is deleted, URLs vanish.
    cleared = client.delete("/api/admin/settings/teaser-video", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["teaser"]["video_set"] is False
    assert key_two in deleted
    landing = client.get("/api/core/landing").json()
    assert landing["teaser_video_url"] == ""


def test_teaser_video_complete_rejects_a_fake_mp4(client, db, monkeypatch):
    from tests.conftest import auth_headers

    _fake_storage(monkeypatch, magic=b"XXXX")  # no ftyp box
    headers = auth_headers(_operator(db))
    url = client.post(
        "/api/admin/settings/teaser-video/upload-url",
        headers=headers,
        json={
            "kind": "video",
            "filename": "fake.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    )
    refused = client.post(
        "/api/admin/settings/teaser-video/complete",
        headers=headers,
        json={"key": url.json()["key"], "poster_key": "", "name": "fake.mp4"},
    )
    assert refused.status_code == 422
    assert teaser.video_state(db)["set"] is False
    # A key outside the teaser namespace is refused outright.
    alien = client.post(
        "/api/admin/settings/teaser-video/complete",
        headers=headers,
        json={"key": "someone/else/video.mp4", "poster_key": "", "name": "x"},
    )
    assert alien.status_code == 422


# -- the rate limit (LAST in the file: it spends the shared IP budget) ----


def test_unlock_attempts_are_rate_limited(client, db):
    _teaser_on(db)
    statuses = [
        client.post("/api/core/signup-unlock", json={"code": "0000"}).status_code
        for _ in range(8)
    ]
    assert 429 in statuses
    # While limited, even the RIGHT code is refused — the pause is
    # the protection, not the answer.
    limited = client.post(
        "/api/core/signup-unlock", json={"code": teaser.DEFAULT_GATE_CODE}
    )
    assert limited.status_code == 429
    assert limited.headers.get("retry-after")


@pytest.fixture(autouse=True)
def _reset_unlock_limiter():
    """The unlock limiter is a process-wide singleton keyed by IP;
    keep this file's earlier tests from spending each other's
    budget (the rate-limit test itself runs last)."""
    from app.core.rate_limit import signup_unlock_rate_limiter

    signup_unlock_rate_limiter._failures.clear()
    yield
    signup_unlock_rate_limiter._failures.clear()
