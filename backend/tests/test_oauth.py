"""Social login (OAuth 2.0).

Provider HTTP is stubbed at oauth.py's two transport helpers, but the
security-critical logic runs for real: Google id_tokens are signed with
a locally generated RSA key and verified through the actual PyJWT path
(signature, audience, issuer, expiry) with the JWKS client stubbed to
return that key. Facebook's debug_token/me calls are canned. No network.

Account creation goes through service.create_oauth_user, which needs
Postgres nextval() for the account number — SQLite has no sequences,
so _next_account_number is stubbed with a counter (the same reason the
password-signup HTTP test doesn't exist; see test_account_number.py).
"""

import itertools
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import security
from app.core.config import settings
from app.modules.core import models as core_models
from app.modules.core import oauth, service

BASE = "https://app.example.test"
FAILURE_LOCATION = f"{BASE}/login?error=oauth"

GOOGLE_CLIENT_ID = "test-google-client-id"
GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_EMAIL = "oauth.user@example.com"

FACEBOOK_APP_ID = "test-facebook-app-id"
FACEBOOK_EMAIL = "fb.user@example.com"


# -- fixtures -------------------------------------------------------------------
@pytest.fixture(scope="module")
def rsa_private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeJwksClient:
    """Stands in for jwt.PyJWKClient: hands back the test public key."""

    def __init__(self, public_key) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token):  # noqa: ANN001, ANN202
        return SimpleNamespace(key=self._public_key)


def _stub_account_numbers(monkeypatch, start: int) -> None:
    counter = itertools.count(start)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


@pytest.fixture()
def google_configured(monkeypatch, rsa_private_key):
    monkeypatch.setattr(settings, "google_client_id", GOOGLE_CLIENT_ID)
    monkeypatch.setattr(settings, "google_client_secret", "test-google-secret")
    monkeypatch.setattr(settings, "app_base_url", BASE)
    monkeypatch.setattr(
        oauth,
        "_google_jwks_client",
        lambda: _FakeJwksClient(rsa_private_key.public_key()),
    )
    _stub_account_numbers(monkeypatch, 700)
    return rsa_private_key


@pytest.fixture()
def facebook_configured(monkeypatch):
    monkeypatch.setattr(settings, "facebook_app_id", FACEBOOK_APP_ID)
    monkeypatch.setattr(settings, "facebook_app_secret", "test-facebook-secret")
    monkeypatch.setattr(settings, "app_base_url", BASE)
    _stub_account_numbers(monkeypatch, 800)


@pytest.fixture()
def nothing_configured(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    monkeypatch.setattr(settings, "facebook_app_id", "")
    monkeypatch.setattr(settings, "facebook_app_secret", "")
    monkeypatch.setattr(settings, "app_base_url", BASE)


# -- helpers ----------------------------------------------------------------------
def _start(client, provider: str):
    response = client.get(
        f"/api/core/auth/{provider}/start", follow_redirects=False
    )
    assert response.status_code == 302
    location = response.headers["location"]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    return location, query["state"][0]


def _callback(client, provider: str, code: str, state: str):
    return client.get(
        f"/api/core/auth/{provider}/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )


def _success_fragment(response) -> dict[str, str]:
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{BASE}/auth/callback#")
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(location).fragment))


def _google_id_token(private_key, **overrides) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": GOOGLE_ISSUER,
        "aud": GOOGLE_CLIENT_ID,
        "sub": "google-subject-1",
        "iat": now,
        "exp": now + timedelta(minutes=10),
        "email": GOOGLE_EMAIL,
        "email_verified": True,
        "name": "Oauth User",
    }
    claims.update(overrides)
    return jwt.encode(
        claims, private_key, algorithm="RS256", headers={"kid": "test-key-1"}
    )


def _stub_google_exchange(monkeypatch, id_token: str) -> None:
    monkeypatch.setattr(
        oauth, "_post_form", lambda _url, _data: {"id_token": id_token}
    )


def _user_count(db) -> int:
    return len(db.query(core_models.User).all())


# -- discovery + start --------------------------------------------------------------
def test_providers_reflect_configuration(client, nothing_configured, monkeypatch):
    body = client.get("/api/core/auth/providers").json()
    assert body == {"google": False, "facebook": False}

    monkeypatch.setattr(settings, "google_client_id", GOOGLE_CLIENT_ID)
    monkeypatch.setattr(settings, "google_client_secret", "test-google-secret")
    body = client.get("/api/core/auth/providers").json()
    assert body == {"google": True, "facebook": False}

    # Half-configured (id without secret) does not count.
    monkeypatch.setattr(settings, "facebook_app_id", FACEBOOK_APP_ID)
    body = client.get("/api/core/auth/providers").json()
    assert body == {"google": True, "facebook": False}


def test_unconfigured_start_returns_404(client, nothing_configured):
    assert client.get("/api/core/auth/google/start").status_code == 404
    assert client.get("/api/core/auth/facebook/start").status_code == 404


def test_google_start_redirects_with_signed_state(client, google_configured):
    location, state = _start(client, "google")
    parsed = urllib.parse.urlparse(location)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == oauth.GOOGLE_AUTH_URL
    query = urllib.parse.parse_qs(parsed.query)
    assert query["client_id"] == [GOOGLE_CLIENT_ID]
    assert query["scope"] == ["openid email profile"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [f"{BASE}/api/core/auth/google/callback"]
    # The state token is ours, current, and bound to THIS provider.
    assert security.verify_oauth_state_token(state, "google") is True
    assert security.verify_oauth_state_token(state, "facebook") is False


def test_facebook_start_redirects_with_signed_state(client, facebook_configured):
    location, state = _start(client, "facebook")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert query["client_id"] == [FACEBOOK_APP_ID]
    assert query["redirect_uri"] == [f"{BASE}/api/core/auth/facebook/callback"]
    assert security.verify_oauth_state_token(state, "facebook") is True


# -- callback: state protection -------------------------------------------------------
def test_callback_rejects_state_from_another_provider(
    client, google_configured, monkeypatch, rsa_private_key
):
    _stub_google_exchange(monkeypatch, _google_id_token(rsa_private_key))
    foreign_state = security.create_oauth_state_token("facebook")
    response = _callback(client, "google", "code-123", foreign_state)
    assert response.status_code == 302
    assert response.headers["location"] == FAILURE_LOCATION


def test_callback_rejects_garbage_and_missing_state(
    client, google_configured, db
):
    response = _callback(client, "google", "code-123", "not-a-real-token")
    assert response.headers["location"] == FAILURE_LOCATION
    response = client.get(
        "/api/core/auth/google/callback",
        params={"code": "code-123"},
        follow_redirects=False,
    )
    assert response.headers["location"] == FAILURE_LOCATION
    assert _user_count(db) == 0


def test_callback_rejects_provider_error_param(client, google_configured):
    _, state = _start(client, "google")
    response = client.get(
        "/api/core/auth/google/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )
    assert response.headers["location"] == FAILURE_LOCATION


# -- callback: Google identity verification --------------------------------------------
def test_google_unverified_email_is_rejected(
    client, google_configured, monkeypatch, rsa_private_key, db
):
    token = _google_id_token(rsa_private_key, email_verified=False)
    _stub_google_exchange(monkeypatch, token)
    _, state = _start(client, "google")
    response = _callback(client, "google", "code-123", state)
    assert response.headers["location"] == FAILURE_LOCATION
    assert service.get_user_by_email(db, GOOGLE_EMAIL) is None


def test_google_wrong_audience_is_rejected(
    client, google_configured, monkeypatch, rsa_private_key, db
):
    token = _google_id_token(rsa_private_key, aud="some-other-apps-client-id")
    _stub_google_exchange(monkeypatch, token)
    _, state = _start(client, "google")
    response = _callback(client, "google", "code-123", state)
    assert response.headers["location"] == FAILURE_LOCATION
    assert _user_count(db) == 0


def test_google_expired_token_is_rejected(
    client, google_configured, monkeypatch, rsa_private_key, db
):
    now = datetime.now(timezone.utc)
    token = _google_id_token(
        rsa_private_key,
        iat=now - timedelta(hours=1),
        exp=now - timedelta(minutes=30),
    )
    _stub_google_exchange(monkeypatch, token)
    _, state = _start(client, "google")
    response = _callback(client, "google", "code-123", state)
    assert response.headers["location"] == FAILURE_LOCATION
    assert _user_count(db) == 0


# -- callback: account resolution ---------------------------------------------------------
def test_google_signup_creates_verified_user_with_account_number(
    client, google_configured, monkeypatch, rsa_private_key, db
):
    _stub_google_exchange(monkeypatch, _google_id_token(rsa_private_key))
    _, state = _start(client, "google")
    fragment = _success_fragment(_callback(client, "google", "code-123", state))

    user = service.get_user_by_email(db, GOOGLE_EMAIL)
    assert user is not None
    assert user.account_number == "TV-000700"
    assert user.email_verified is True
    assert user.name == "Oauth User"
    # The issued pair is real: the access token names this user, and the
    # refresh token rotates through the normal session machinery.
    assert security.decode_access_token(fragment["access_token"]) == str(user.id)
    rotated = service.rotate_refresh_token(db, fragment["refresh_token"])
    assert rotated is not None and rotated[0].id == user.id
    # No usable password: password login can never succeed.
    assert service.authenticate(db, GOOGLE_EMAIL, "any-password-at-all") is None


def test_google_signin_matches_existing_user_by_email(
    client, google_configured, monkeypatch, rsa_private_key, db
):
    existing = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-000042",
        email=GOOGLE_EMAIL,
        name="Migrated App User",
        password_hash="not-a-real-hash",
        email_verified=False,
    )
    db.add(existing)
    db.commit()

    _stub_google_exchange(monkeypatch, _google_id_token(rsa_private_key))
    _, state = _start(client, "google")
    fragment = _success_fragment(_callback(client, "google", "code-123", state))

    # Same account — no duplicate, number untouched, now verified.
    assert _user_count(db) == 1
    assert security.decode_access_token(fragment["access_token"]) == str(existing.id)
    db.refresh(existing)
    assert existing.account_number == "TV-000042"
    assert existing.email_verified is True


# -- kept destination (sweep C2 completion) -------------------------------------------
def _start_with_next(client, provider: str, next_value: str):
    response = client.get(
        f"/api/core/auth/{provider}/start",
        params={"next": next_value},
        follow_redirects=False,
    )
    assert response.status_code == 302
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(response.headers["location"]).query
    )
    return query["state"][0]


def test_google_next_destination_survives_the_round_trip(
    client, google_configured, monkeypatch, rsa_private_key, db
):
    # The sign-in door's kept destination is sealed in the signed
    # state token at start and handed back in the success fragment.
    dest = "/forum/thread/3b456a2f?from=share#opener"
    state = _start_with_next(client, "google", dest)
    assert security.read_oauth_state_next(state, "google") == dest
    # Provider-bound: the same token read for Facebook yields nothing.
    assert security.read_oauth_state_next(state, "facebook") is None

    _stub_google_exchange(monkeypatch, _google_id_token(rsa_private_key))
    fragment = _success_fragment(_callback(client, "google", "code-123", state))
    assert fragment["next"] == dest


def test_google_unsafe_next_is_dropped_at_start(
    client, google_configured, monkeypatch, rsa_private_key, db
):
    # Off-site / protocol-relative / backslash destinations never
    # enter the token, and the success fragment stays bare.
    for evil in (
        "https://evil.example/phish",
        "//evil.example/phish",
        "/\\evil.example",
        "javascript:alert(1)",
    ):
        state = _start_with_next(client, "google", evil)
        assert security.read_oauth_state_next(state, "google") is None

    _stub_google_exchange(monkeypatch, _google_id_token(rsa_private_key))
    state = _start_with_next(client, "google", "https://evil.example/phish")
    fragment = _success_fragment(_callback(client, "google", "code-123", state))
    assert "next" not in fragment


def test_google_plain_start_carries_no_destination(
    client, google_configured, monkeypatch, rsa_private_key, db
):
    # Regression: a start with no ?next= mints the old plain state
    # token and the success fragment is exactly tokens-only.
    _, state = _start(client, "google")
    assert security.read_oauth_state_next(state, "google") is None
    _stub_google_exchange(monkeypatch, _google_id_token(rsa_private_key))
    fragment = _success_fragment(_callback(client, "google", "code-123", state))
    assert set(fragment) == {"access_token", "refresh_token"}


# -- callback: Facebook ---------------------------------------------------------------------
def _stub_facebook(monkeypatch, *, me_payload, debug_valid=True, debug_app_id=FACEBOOK_APP_ID):
    def fake_get(url, _params):
        if "oauth/access_token" in url:
            return {"access_token": "fb-user-token"}
        if "debug_token" in url:
            return {"data": {"is_valid": debug_valid, "app_id": debug_app_id}}
        if url == oauth.FACEBOOK_ME_URL:
            return me_payload
        raise AssertionError(f"unexpected provider URL: {url}")

    monkeypatch.setattr(oauth, "_get_json", fake_get)


def test_facebook_signup_creates_verified_user(
    client, facebook_configured, monkeypatch, db
):
    _stub_facebook(
        monkeypatch,
        me_payload={"id": "fb-1", "name": "Fb User", "email": FACEBOOK_EMAIL},
    )
    _, state = _start(client, "facebook")
    fragment = _success_fragment(_callback(client, "facebook", "code-9", state))

    user = service.get_user_by_email(db, FACEBOOK_EMAIL)
    assert user is not None
    assert user.account_number == "TV-000800"
    assert user.email_verified is True
    assert security.decode_access_token(fragment["access_token"]) == str(user.id)


def test_facebook_without_email_is_rejected(
    client, facebook_configured, monkeypatch, db
):
    _stub_facebook(monkeypatch, me_payload={"id": "fb-2", "name": "No Email"})
    _, state = _start(client, "facebook")
    response = _callback(client, "facebook", "code-9", state)
    assert response.headers["location"] == FAILURE_LOCATION
    assert _user_count(db) == 0


def test_facebook_token_for_another_app_is_rejected(
    client, facebook_configured, monkeypatch, db
):
    _stub_facebook(
        monkeypatch,
        me_payload={"id": "fb-3", "name": "Fb User", "email": FACEBOOK_EMAIL},
        debug_app_id="a-different-app",
    )
    _, state = _start(client, "facebook")
    response = _callback(client, "facebook", "code-9", state)
    assert response.headers["location"] == FAILURE_LOCATION
    assert _user_count(db) == 0


def test_facebook_invalid_token_is_rejected(
    client, facebook_configured, monkeypatch, db
):
    _stub_facebook(
        monkeypatch,
        me_payload={"id": "fb-4", "name": "Fb User", "email": FACEBOOK_EMAIL},
        debug_valid=False,
    )
    _, state = _start(client, "facebook")
    response = _callback(client, "facebook", "code-9", state)
    assert response.headers["location"] == FAILURE_LOCATION
    assert _user_count(db) == 0
