"""Social login (OAuth 2.0): provider configuration + identity verification.

This module answers two questions for oauth_routes.py:
  1. "Is this provider configured, and where do I send the user?"
  2. "The provider sent the user back with a code — who are they?"

Question 2 never takes the provider's word at face value:
  - Google's id_token is cryptographically verified — signature against
    Google's JWKS, audience == our client id, issuer, expiry — and the
    email must be marked verified by Google.
  - Facebook's user token is validated through debug_token against OUR
    app credentials (it must be valid and issued for this app) before
    /me is read, and /me must contain an email.

The local account side (find-or-create by verified email, session
issuance) lives in service.py; this module only talks to providers.
Provider HTTP goes through the two small helpers below so tests can
stub the transport without touching the verification logic.
"""

import urllib.parse

import httpx
import jwt

from app.core.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

FACEBOOK_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
FACEBOOK_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"
FACEBOOK_DEBUG_TOKEN_URL = "https://graph.facebook.com/debug_token"
FACEBOOK_ME_URL = "https://graph.facebook.com/me"

_HTTP_TIMEOUT_SECONDS = 10.0


class OAuthError(Exception):
    """Any provider-side failure. Callers turn it into one generic
    "sign-in didn't work" redirect — details never reach the user."""


# -- configuration -----------------------------------------------------------
def google_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def facebook_configured() -> bool:
    return bool(settings.facebook_app_id and settings.facebook_app_secret)


def configured_providers() -> dict[str, bool]:
    return {"google": google_configured(), "facebook": facebook_configured()}


def _callback_url(provider: str) -> str:
    return f"{settings.app_base_url}/api/core/auth/{provider}/callback"


def google_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _callback_url("google"),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def facebook_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.facebook_app_id,
        "redirect_uri": _callback_url("facebook"),
        "response_type": "code",
        "scope": "email,public_profile",
        "state": state,
    }
    return f"{FACEBOOK_AUTH_URL}?{urllib.parse.urlencode(params)}"


# -- provider HTTP (stubbed in tests) -----------------------------------------
def _post_form(url: str, data: dict[str, str]) -> dict:
    try:
        response = httpx.post(url, data=data, timeout=_HTTP_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise OAuthError(f"POST {url} failed: {exc}") from exc
    return _json_or_raise(response, f"POST {url}")


def _get_json(url: str, params: dict[str, str]) -> dict:
    try:
        response = httpx.get(url, params=params, timeout=_HTTP_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise OAuthError(f"GET {url} failed: {exc}") from exc
    return _json_or_raise(response, f"GET {url}")


def _json_or_raise(response: httpx.Response, label: str) -> dict:
    if response.status_code != 200:
        raise OAuthError(f"{label} returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise OAuthError(f"{label} returned non-JSON") from exc
    if not isinstance(payload, dict):
        raise OAuthError(f"{label} returned an unexpected payload")
    return payload


# -- Google --------------------------------------------------------------------
_jwks_client: jwt.PyJWKClient | None = None


def _google_jwks_client() -> jwt.PyJWKClient:
    """Google's signing-key client, built once per process (it caches
    the keys it fetches and refreshes them on rotation)."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(GOOGLE_JWKS_URL)
    return _jwks_client


def authenticate_google(code: str) -> dict[str, str]:
    """Exchange `code` at Google; return {"email", "name"} from the
    VERIFIED id_token. Raises OAuthError on any failure."""
    token_response = _post_form(
        GOOGLE_TOKEN_URL,
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _callback_url("google"),
        },
    )
    id_token = token_response.get("id_token")
    if not id_token:
        raise OAuthError("Google token response had no id_token")
    try:
        signing_key = _google_jwks_client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=GOOGLE_ISSUERS,
            options={"require": ["exp", "iss", "aud", "sub", "email"]},
        )
    except jwt.PyJWTError as exc:
        raise OAuthError(f"Google id_token failed verification: {exc}") from exc
    # Google normally sends a JSON boolean; accept the string form too.
    if claims.get("email_verified") not in (True, "true"):
        raise OAuthError("Google account email is not verified")
    return {"email": claims["email"], "name": claims.get("name", "")}


# -- Facebook ------------------------------------------------------------------
def authenticate_facebook(code: str) -> dict[str, str]:
    """Exchange `code` at Facebook, validate the resulting user token
    against OUR app via debug_token, and return {"email", "name"} from
    /me. Raises OAuthError on any failure."""
    token_response = _get_json(
        FACEBOOK_TOKEN_URL,
        {
            "client_id": settings.facebook_app_id,
            "client_secret": settings.facebook_app_secret,
            "code": code,
            "redirect_uri": _callback_url("facebook"),
        },
    )
    access_token = token_response.get("access_token")
    if not access_token:
        raise OAuthError("Facebook token response had no access_token")
    app_token = f"{settings.facebook_app_id}|{settings.facebook_app_secret}"
    debug = _get_json(
        FACEBOOK_DEBUG_TOKEN_URL,
        {"input_token": access_token, "access_token": app_token},
    )
    data = debug.get("data") or {}
    if data.get("is_valid") is not True or str(data.get("app_id")) != (
        settings.facebook_app_id
    ):
        raise OAuthError("Facebook token failed debug_token validation")
    me = _get_json(
        FACEBOOK_ME_URL,
        {"fields": "id,name,email", "access_token": access_token},
    )
    email = me.get("email")
    if not email:
        raise OAuthError("Facebook account has no email address")
    return {"email": email, "name": me.get("name", "")}
