"""Email flows (email phase, 2026-10-18): the provider seam and its
outbox, password reset, email change, verification resend, and the
verification-gating launch switch.

The fake transport is the OUTBOX itself: in dev mode every send is
recorded whole (recipient, subject, body — link and token
included), so the happy paths run the real request → read the
"email" → follow the link cycle exactly as a user's inbox would.
Resend-mode tests stub httpx at the seam (notifications.httpx.post)
— the network is never touched.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.core import notifications
from app.core.config import settings
from app.core.security import generate_opaque_token
from app.modules.billing import entitlements
from app.modules.core import models, service
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    """service.create_user (and HTTP signup through it) allocates
    account numbers from a Postgres sequence SQLite doesn't have;
    the suite's established stub (test_change_password.py,
    test_admin_panel.py) swaps in a counter so the REAL creation
    paths run end-to-end here."""
    counter = itertools.count(900_000)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _email(tag: str) -> str:
    """A unique address per test: the email-send rate limiter is
    process-global, so tests never share an address (or its keys)."""
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(client, email: str, password: str = "hunter2!"):
    response = client.post(
        "/api/core/signup",
        json={
            "email": email,
            "name": "Flow Tester",
            "password": password,
            "account_types": ["mechanic_technician"],
            "country": "US",
            "currency": "USD",
            "locale": "en",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(client, email: str, password: str):
    return client.post(
        "/api/core/login", json={"email": email, "password": password}
    )


def _outbox(db, *, kind: str | None = None, recipient: str | None = None):
    stmt = select(models.EmailOutbox)
    if kind is not None:
        stmt = stmt.where(models.EmailOutbox.kind == kind)
    if recipient is not None:
        stmt = stmt.where(models.EmailOutbox.recipient == recipient)
    return list(db.scalars(stmt).all())


def _token_from(body: str) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", body)
    assert match, f"no token link in body: {body!r}"
    return match.group(1)


def _reset_token_for(db, email: str) -> str:
    rows = _outbox(db, kind="password_reset", recipient=email)
    assert len(rows) == 1
    return _token_from(rows[0].body)


# -- the seam + outbox ---------------------------------------------------------


def test_dev_send_records_outbox_row(db):
    ok = notifications.send_email(
        db, "someone@example.com", "Hello", "Body text", kind="generic"
    )
    assert ok is True
    rows = _outbox(db, recipient="someone@example.com")
    assert len(rows) == 1
    row = rows[0]
    assert (row.subject, row.kind, row.provider, row.status) == (
        "Hello",
        "generic",
        "dev",
        "logged",
    )


def test_resend_provider_success_records_sent(db, monkeypatch):
    calls = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.update(url=url, headers=headers, json=json)
        return SimpleNamespace(status_code=200, text='{"id":"x"}')

    monkeypatch.setattr(settings, "email_provider", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "rk_test_key")
    monkeypatch.setattr(notifications.httpx, "post", fake_post)

    ok = notifications.send_email(db, "a@b.co", "Subj", "Body", kind="generic")
    assert ok is True
    assert calls["url"] == "https://api.resend.com/emails"
    assert calls["headers"]["Authorization"] == "Bearer rk_test_key"
    assert calls["json"]["from"] == settings.email_from
    assert calls["json"]["to"] == ["a@b.co"]
    assert calls["json"]["subject"] == "Subj"
    # The one-template order (2026-11-09) supersedes the old pin
    # (text == the raw body): the payload's text part IS the
    # templated text — greeting + content + footer — and an HTML
    # part rides beside it. a@b.co has no account: fallback greeting.
    assert calls["json"]["text"].startswith("Hi there,")
    assert "\nBody\n" in calls["json"]["text"]
    assert "Toolbox Vault" in calls["json"]["html"]
    row = _outbox(db, recipient="a@b.co")[0]
    assert (row.provider, row.status) == ("resend", "sent")


def test_resend_provider_failure_records_failed_and_never_raises(db, monkeypatch):
    monkeypatch.setattr(settings, "email_provider", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "rk_test_key")
    monkeypatch.setattr(
        notifications.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(status_code=500, text="nope"),
    )
    assert notifications.send_email(db, "a@b.co", "S", "B") is False
    assert _outbox(db, recipient="a@b.co")[0].status == "failed"

    def boom(*a, **k):
        raise httpx.ConnectError(
            "down", request=httpx.Request("POST", "https://api.resend.com/emails")
        )

    monkeypatch.setattr(notifications.httpx, "post", boom)
    assert notifications.send_email(db, "c@d.co", "S", "B") is False
    assert _outbox(db, recipient="c@d.co")[0].status == "failed"


def test_resend_provider_without_key_is_a_recorded_failure(db, monkeypatch):
    monkeypatch.setattr(settings, "email_provider", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "")
    assert notifications.send_email(db, "a@b.co", "S", "B") is False
    row = _outbox(db, recipient="a@b.co")[0]
    assert (row.provider, row.status) == ("resend", "failed")


# -- password reset ------------------------------------------------------------


def test_password_reset_happy_path(db, client):
    email = _email("reset-happy")
    _signup(client, email, password="old-pass-1")
    tokens = _login(client, email, "old-pass-1").json()

    response = client.post("/api/core/password-reset/request", json={"email": email})
    assert response.status_code == 200
    rows = _outbox(db, kind="password_reset", recipient=email)
    assert len(rows) == 1
    assert (rows[0].provider, rows[0].status) == ("dev", "logged")
    assert "/reset-password?token=" in rows[0].body

    confirm = client.post(
        "/api/core/password-reset/confirm",
        json={"token": _token_from(rows[0].body), "new_password": "new-pass-2"},
    )
    assert confirm.status_code == 200

    # The old password is dead, the new one works…
    assert _login(client, email, "old-pass-1").status_code == 401
    assert _login(client, email, "new-pass-2").status_code == 200
    # …and every session from before the reset is revoked.
    refreshed = client.post(
        "/api/core/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 401


def test_password_reset_request_is_not_an_existence_oracle(db, client):
    email = _email("reset-oracle")
    _signup(client, email)
    ghost = _email("reset-ghost")
    real = client.post("/api/core/password-reset/request", json={"email": email})
    fake = client.post("/api/core/password-reset/request", json={"email": ghost})
    assert real.status_code == fake.status_code == 200
    assert real.json() == fake.json()
    assert _outbox(db, kind="password_reset", recipient=ghost) == []


def test_password_reset_new_request_supersedes_the_old_link(db, client):
    email = _email("reset-supersede")
    _signup(client, email)
    client.post("/api/core/password-reset/request", json={"email": email})
    first = _reset_token_for(db, email)
    client.post("/api/core/password-reset/request", json={"email": email})
    rows = _outbox(db, kind="password_reset", recipient=email)
    assert len(rows) == 2
    second = next(
        _token_from(r.body) for r in rows if _token_from(r.body) != first
    )
    stale = client.post(
        "/api/core/password-reset/confirm",
        json={"token": first, "new_password": "whatever-1"},
    )
    assert stale.status_code == 400
    assert "already used" in stale.json()["detail"]
    fresh = client.post(
        "/api/core/password-reset/confirm",
        json={"token": second, "new_password": "whatever-1"},
    )
    assert fresh.status_code == 200


def test_password_reset_token_is_single_use(db, client):
    email = _email("reset-once")
    _signup(client, email)
    client.post("/api/core/password-reset/request", json={"email": email})
    token = _reset_token_for(db, email)
    body = {"token": token, "new_password": "brand-new-1"}
    assert client.post("/api/core/password-reset/confirm", json=body).status_code == 200
    again = client.post("/api/core/password-reset/confirm", json=body)
    assert again.status_code == 400
    assert "already used" in again.json()["detail"]


def test_password_reset_unknown_and_expired_tokens(db, client):
    email = _email("reset-expired")
    _signup(client, email)
    user = service.get_user_by_email(db, email)

    bogus = client.post(
        "/api/core/password-reset/confirm",
        json={"token": "no-such-token", "new_password": "whatever-1"},
    )
    assert bogus.status_code == 400
    assert "invalid" in bogus.json()["detail"]

    plain, token_hash = generate_opaque_token()
    db.add(
        models.PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    db.commit()
    expired = client.post(
        "/api/core/password-reset/confirm",
        json={"token": plain, "new_password": "whatever-1"},
    )
    assert expired.status_code == 400
    assert "expired" in expired.json()["detail"]


def test_password_reset_short_password_is_a_422(db, client):
    response = client.post(
        "/api/core/password-reset/confirm",
        json={"token": "anything", "new_password": "12345"},
    )
    assert response.status_code == 422


def test_password_reset_banned_account_silence_and_blocked_confirm(db, client):
    email = _email("reset-banned")
    _signup(client, email, password="keep-me-1")
    client.post("/api/core/password-reset/request", json={"email": email})
    token = _reset_token_for(db, email)

    service.ban_email(db, email, reason="test ban")
    # Requesting again: same generic 200, and NO new email goes out.
    again = client.post("/api/core/password-reset/request", json={"email": email})
    assert again.status_code == 200
    assert len(_outbox(db, kind="password_reset", recipient=email)) == 1
    # The link minted before the ban can't be used under it.
    confirm = client.post(
        "/api/core/password-reset/confirm",
        json={"token": token, "new_password": "sneak-in-1"},
    )
    assert confirm.status_code == 403
    # Password untouched: unban and the original still signs in.
    service.unban_email(db, email)
    assert _login(client, email, "keep-me-1").status_code == 200
    assert _login(client, email, "sneak-in-1").status_code == 401


def test_password_reset_requests_are_rate_limited(db, client):
    email = _email("reset-flood")
    _signup(client, email)
    for _ in range(5):
        ok = client.post("/api/core/password-reset/request", json={"email": email})
        assert ok.status_code == 200
    sixth = client.post("/api/core/password-reset/request", json={"email": email})
    assert sixth.status_code == 429


# -- email change --------------------------------------------------------------


def _user_with_password(db, email: str, password: str = "current-1"):
    return service.create_user(
        db, email, "Change Tester", password, ["mechanic_technician"]
    )


def test_email_change_full_cycle(db, client):
    old_email = _email("change-old")
    new_email = _email("change-new")
    user = _user_with_password(db, old_email)
    headers = auth_headers(user)

    started = client.post(
        "/api/core/email-change/request",
        json={"new_email": new_email, "current_password": "current-1"},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    assert started.json()["pending_email"] == new_email

    state = client.get("/api/core/email-change", headers=headers)
    assert state.json()["pending_email"] == new_email

    # The link went to the NEW address; the account hasn't moved yet.
    rows = _outbox(db, kind="email_change", recipient=new_email)
    assert len(rows) == 1
    token = _token_from(rows[0].body)
    assert service.get_user_by_email(db, old_email) is not None

    confirm = client.post(
        "/api/core/email-change/confirm", json={"token": token}
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["email"] == new_email

    me = client.get("/api/core/me", headers=headers)
    assert me.json()["email"] == new_email
    assert me.json()["email_verified"] is True

    # The OLD address got the tripwire notice…
    notices = _outbox(db, kind="email_changed_notice", recipient=old_email)
    assert len(notices) == 1
    assert new_email in notices[0].body
    # …the move is in the audit trail…
    audit_rows = list(
        db.scalars(
            select(models.AuditLog).where(
                models.AuditLog.action == "user.email_change"
            )
        ).all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].target == new_email
    assert audit_rows[0].detail == {"from": old_email, "to": new_email}
    # …and sign-in follows the new address.
    assert _login(client, old_email, "current-1").status_code == 401
    assert _login(client, new_email, "current-1").status_code == 200

    # The consumed link is dead.
    again = client.post("/api/core/email-change/confirm", json={"token": token})
    assert again.status_code == 400
    assert "already used" in again.json()["detail"]


def test_email_change_rejections(db, client):
    email = _email("change-reject")
    user = _user_with_password(db, email)
    headers = auth_headers(user)
    other = _user_with_password(db, _email("change-other"))

    wrong_pw = client.post(
        "/api/core/email-change/request",
        json={"new_email": _email("change-x"), "current_password": "nope-nope"},
        headers=headers,
    )
    assert wrong_pw.status_code == 400
    assert "Current password is incorrect" in wrong_pw.json()["detail"]

    same = client.post(
        "/api/core/email-change/request",
        json={"new_email": email, "current_password": "current-1"},
        headers=headers,
    )
    assert same.status_code == 400
    assert "already your email" in same.json()["detail"]

    taken = client.post(
        "/api/core/email-change/request",
        json={"new_email": other.email, "current_password": "current-1"},
        headers=headers,
    )
    assert taken.status_code == 409

    banned_target = _email("change-banned-target")
    service.ban_email(db, banned_target, reason="test ban")
    banned = client.post(
        "/api/core/email-change/request",
        json={"new_email": banned_target, "current_password": "current-1"},
        headers=headers,
    )
    assert banned.status_code == 403
    # Nothing was ever left pending by the refusals.
    state = client.get("/api/core/email-change", headers=headers)
    assert state.json()["pending_email"] is None


def test_email_change_oauth_account_needs_no_current_password(db, client):
    user = service.create_oauth_user(db, _email("change-oauth"), "OAuth User")
    headers = auth_headers(user)
    new_email = _email("change-oauth-new")
    started = client.post(
        "/api/core/email-change/request",
        json={"new_email": new_email},
        headers=headers,
    )
    assert started.status_code == 200
    assert started.json()["pending_email"] == new_email


def test_email_change_cancel_kills_the_link(db, client):
    user = _user_with_password(db, _email("change-cancel"))
    headers = auth_headers(user)
    new_email = _email("change-cancel-new")
    client.post(
        "/api/core/email-change/request",
        json={"new_email": new_email, "current_password": "current-1"},
        headers=headers,
    )
    token = _token_from(_outbox(db, kind="email_change", recipient=new_email)[0].body)
    assert client.delete("/api/core/email-change", headers=headers).status_code == 204
    state = client.get("/api/core/email-change", headers=headers)
    assert state.json()["pending_email"] is None
    confirm = client.post("/api/core/email-change/confirm", json={"token": token})
    assert confirm.status_code == 400


def test_email_change_confirm_rechecks_taken(db, client):
    user = _user_with_password(db, _email("change-race"))
    headers = auth_headers(user)
    new_email = _email("change-race-new")
    client.post(
        "/api/core/email-change/request",
        json={"new_email": new_email, "current_password": "current-1"},
        headers=headers,
    )
    token = _token_from(_outbox(db, kind="email_change", recipient=new_email)[0].body)
    # Someone else claims the address before the link is clicked.
    _signup(client, new_email)
    confirm = client.post("/api/core/email-change/confirm", json={"token": token})
    assert confirm.status_code == 409
    db.refresh(user)
    assert user.email != new_email


def test_email_change_keeps_confirming_session_revokes_others(db, client):
    old_email = _email("change-sessions")
    _signup(client, old_email, password="current-1")
    first = _login(client, old_email, "current-1").json()
    second = _login(client, old_email, "current-1").json()
    headers = {"Authorization": f"Bearer {first['access_token']}"}
    new_email = _email("change-sessions-new")
    client.post(
        "/api/core/email-change/request",
        json={"new_email": new_email, "current_password": "current-1"},
        headers=headers,
    )
    token = _token_from(_outbox(db, kind="email_change", recipient=new_email)[0].body)
    confirm = client.post(
        "/api/core/email-change/confirm",
        json={"token": token, "refresh_token": first["refresh_token"]},
    )
    assert confirm.status_code == 200
    kept = client.post(
        "/api/core/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert kept.status_code == 200
    revoked = client.post(
        "/api/core/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert revoked.status_code == 401


# -- verification resend -------------------------------------------------------


def test_resend_verification_public_is_generic(db, client):
    email = _email("resend-public")
    _signup(client, email)  # unverified; signup already sent one link
    before = len(_outbox(db, kind="verification", recipient=email))
    assert before == 1

    real = client.post("/api/core/resend-verification", json={"email": email})
    assert real.status_code == 200
    assert len(_outbox(db, kind="verification", recipient=email)) == 2

    ghost = _email("resend-ghost")
    fake = client.post("/api/core/resend-verification", json={"email": ghost})
    assert fake.status_code == 200
    assert fake.json() == real.json()
    assert _outbox(db, kind="verification", recipient=ghost) == []


def test_resend_my_verification(db, client):
    user = _user_with_password(db, _email("resend-mine"))
    headers = auth_headers(user)
    assert client.post("/api/core/me/resend-verification", headers=headers).status_code == 204
    assert len(_outbox(db, kind="verification", recipient=user.email)) == 1
    # Once verified, resending for yourself is a no-op.
    token = _token_from(_outbox(db, kind="verification", recipient=user.email)[0].body)
    assert service.verify_email(db, token) is True
    assert client.post("/api/core/me/resend-verification", headers=headers).status_code == 204
    assert len(_outbox(db, kind="verification", recipient=user.email)) == 1


# -- verification gating (the launch switch) -------------------------------------


def _enable_gating(db):
    entitlements.set_setting(db, entitlements.REQUIRE_EMAIL_VERIFICATION_KEY, True)


def test_gating_off_by_default_unverified_login_works(db, client):
    email = _email("gate-off")
    _signup(client, email, password="open-sesame-1")
    assert _login(client, email, "open-sesame-1").status_code == 200


def test_gating_on_blocks_unverified_until_they_verify(db, client):
    email = _email("gate-on")
    _signup(client, email, password="open-sesame-1")
    _enable_gating(db)

    blocked = _login(client, email, "open-sesame-1")
    assert blocked.status_code == 403
    detail = blocked.json()["detail"]
    assert detail["code"] == "email_unverified"

    rows = _outbox(db, kind="verification", recipient=email)
    assert service.verify_email(db, _token_from(rows[0].body)) is True
    assert _login(client, email, "open-sesame-1").status_code == 200


def test_gating_on_never_blocks_oauth_accounts(db, client):
    # OAuth accounts are provider-verified at creation; one that
    # later sets a password signs in with it unimpeded.
    user = service.create_oauth_user(db, _email("gate-oauth"), "OAuth User")
    assert service.change_password(db, user, None, "set-later-1", None) is True
    _enable_gating(db)
    assert _login(client, user.email, "set-later-1").status_code == 200
