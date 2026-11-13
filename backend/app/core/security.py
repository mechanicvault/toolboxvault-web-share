"""Centralized security primitives: password hashing and JWT sessions.

The ONLY place passwords are hashed/verified and tokens are minted/decoded.
Modules call these functions; they never touch argon2 or JWT libraries
directly. Opaque tokens (refresh, email verification) are also minted and
hashed here — callers store only the hash.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_ph = PasswordHasher()


def hash_password(plain: str) -> str:
    """Hash a password with argon2. Store the result, never the plain text."""
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if the plain password matches the stored hash."""
    try:
        _ph.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False


def create_access_token(subject: str) -> str:
    """Mint a short-lived JWT identifying the user id in `subject`."""
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """Return the user id from a valid token, or None if invalid/expired."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return str(payload["sub"])
    except jwt.PyJWTError:
        return None


# -- OAuth state tokens ------------------------------------------------------
# The `state` parameter on social-login redirects: a short-lived signed
# JWT proving the round trip started here, recently, for THIS provider
# (CSRF / provider mix-up protection). Purpose- and provider-bound, and
# useless as an access token — it carries no `sub` claim.

def safe_local_next_path(value: object) -> str | None:
    """Validate a return destination for the OAuth round trip.

    Only a same-site path may ride along: exactly one leading
    slash (never ``//`` — a protocol-relative URL), no backslash
    (browsers treat ``/\\`` as ``//``), no control characters,
    bounded length. Anything else reads as "no destination" —
    the caller falls back to the default home, never to the
    supplied value. The same check runs when the destination is
    minted into the state token and again when it is read back,
    so a hand-crafted token or fragment cannot smuggle an
    off-site redirect past either end."""
    if not isinstance(value, str) or not value:
        return None
    if len(value) > 2048:
        return None
    if not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value:
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return None
    return value


def create_oauth_state_token(provider: str, next_path: str | None = None) -> str:
    """Mint a signed state token for one OAuth round trip.

    Sweep C2 completion (2026-11-12): an optional kept destination
    (the sign-in door's `state.from`) rides INSIDE the signed
    token as a `next` claim — the one channel that provably
    survives the provider round trip, since the provider echoes
    `state` back verbatim. Only a validated same-site path is
    embedded (see safe_local_next_path); anything else mints a
    plain state token exactly as before."""
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.oauth_state_expire_minutes
    )
    payload = {
        "purpose": "oauth_state",
        "provider": provider,
        "jti": secrets.token_urlsafe(16),
        "exp": expires,
    }
    safe_next = safe_local_next_path(next_path)
    if safe_next is not None:
        payload["next"] = safe_next
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_oauth_state_token(token: str, provider: str) -> bool:
    """True only for a valid, unexpired state token minted for `provider`."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return False
    return (
        payload.get("purpose") == "oauth_state"
        and payload.get("provider") == provider
    )


def read_oauth_state_next(token: str, provider: str) -> str | None:
    """The kept destination carried by a valid state token, or None.

    Re-verifies the token (signature, expiry, purpose, provider)
    and re-validates the claim, so callers can trust the result
    as a same-site path. A token minted before destinations rode
    along simply has no claim and reads as None."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None
    if (
        payload.get("purpose") != "oauth_state"
        or payload.get("provider") != provider
    ):
        return None
    return safe_local_next_path(payload.get("next"))


# -- signup unlock tokens (teaser gate, 2026-10-26) ------------------------
# While teaser mode is on (core/teaser.py), account creation is
# gated behind a code the operator holds. Trading the right code
# mints one of these: a signed, purpose-scoped token carried in an
# httpOnly cookie. It unlocks NOTHING but the two signup doors,
# and it dies in 30 minutes — the code itself never leaves the
# server and never appears in any client payload.

SIGNUP_UNLOCK_TTL_MINUTES = 30


def create_signup_unlock_token() -> str:
    """Mint a signed token proving the bearer passed the teaser signup gate."""
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=SIGNUP_UNLOCK_TTL_MINUTES
    )
    payload = {
        "purpose": "signup_unlock",
        "jti": secrets.token_urlsafe(16),
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_signup_unlock_token(token: str | None) -> bool:
    """True only for a valid, unexpired signup-unlock token."""
    if not token:
        return False
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return False
    return payload.get("purpose") == "signup_unlock"


# -- visitor-counted tokens (teaser visitor counter, 2026-10-26) -----------
# The teaser page's visitor counter counts UNIQUE browsers, once:
# the count endpoint (core/teaser.py) mints one of these into an
# httpOnly cookie the first time it counts a browser, and a valid
# one is the whole proof that this browser was already counted.
# Purpose-scoped like the unlock token, useless for anything else
# (no `sub`, no doors opened) — it just has to live long, because
# a counter that re-counts every month is not a unique counter.

VISITOR_TOKEN_TTL_DAYS = 365


def create_visitor_token() -> str:
    """Mint a signed token marking the bearer as already counted."""
    expires = datetime.now(timezone.utc) + timedelta(days=VISITOR_TOKEN_TTL_DAYS)
    payload = {
        "purpose": "visitor_counted",
        "jti": secrets.token_urlsafe(16),
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_visitor_token(token: str | None) -> bool:
    """True only for a valid, unexpired visitor-counted token."""
    if not token:
        return False
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return False
    return payload.get("purpose") == "visitor_counted"


# -- opaque tokens (refresh tokens, email-verification tokens) ------------
# The plain value is shown to the client exactly once; only its SHA-256
# hash is ever stored, so a database leak does not leak usable tokens.

def generate_opaque_token() -> tuple[str, str]:
    """Return (plain_token, token_hash). Store the hash, give out the plain."""
    plain = secrets.token_urlsafe(48)
    return plain, hash_opaque_token(plain)


def hash_opaque_token(plain: str) -> str:
    """SHA-256 hex digest of an opaque token, for lookup/storage."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()
