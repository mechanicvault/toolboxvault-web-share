"""Refresh-token lifecycle (audit I3): rotation, revocation, reuse detection.

Runs on SQLite with the real service functions — the guarantee under test
is behavioral: an old token never works twice, and replaying one kills
the whole family.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import generate_opaque_token, hash_opaque_token
from app.modules.core import models, service


def _stored(db, plain: str) -> models.RefreshToken:
    return db.scalars(
        select(models.RefreshToken).where(
            models.RefreshToken.token_hash == hash_opaque_token(plain)
        )
    ).first()


def test_only_the_hash_is_stored(db, user_a):
    plain = service.issue_refresh_token(db, user_a)
    stored = _stored(db, plain)
    assert stored is not None
    assert stored.token_hash == hash_opaque_token(plain)
    assert stored.token_hash != plain
    assert stored.revoked_at is None


def test_rotation_issues_a_new_token_and_revokes_the_old(db, user_a):
    first = service.issue_refresh_token(db, user_a)
    rotated = service.rotate_refresh_token(db, first)
    assert rotated is not None
    user, second = rotated
    assert user.id == user_a.id
    assert second != first
    old = _stored(db, first)
    assert old.revoked_at is not None
    assert old.replaced_by_id == _stored(db, second).id


def test_rotated_chain_keeps_working(db, user_a):
    plain = service.issue_refresh_token(db, user_a)
    for _ in range(3):
        rotated = service.rotate_refresh_token(db, plain)
        assert rotated is not None
        _, plain = rotated


def test_reuse_of_a_revoked_token_kills_the_family(db, user_a):
    first = service.issue_refresh_token(db, user_a)
    _, second = service.rotate_refresh_token(db, first)
    # Replaying the revoked first token = theft signal.
    assert service.rotate_refresh_token(db, first) is None
    # The legitimate newest token is dead too.
    assert service.rotate_refresh_token(db, second) is None
    assert _stored(db, second).revoked_at is not None


def test_unknown_token_is_rejected(db, user_a):
    assert service.rotate_refresh_token(db, "no-such-token") is None


def test_expired_token_is_rejected(db, user_a):
    plain, token_hash = generate_opaque_token()
    db.add(
        models.RefreshToken(
            user_id=user_a.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    db.commit()
    assert service.rotate_refresh_token(db, plain) is None


def test_logout_revokes_and_is_idempotent(db, user_a):
    plain = service.issue_refresh_token(db, user_a)
    service.revoke_refresh_token(db, plain)
    assert _stored(db, plain).revoked_at is not None
    assert service.rotate_refresh_token(db, plain) is None
    # Second logout / unknown token: no error, no oracle.
    service.revoke_refresh_token(db, plain)
    service.revoke_refresh_token(db, "never-issued")


def test_user_revoked_token_does_not_kill_sibling_session(db, user_a):
    """Deep audit F4-01: logging out on one device must not sign the
    user out everywhere when the logged-out device retries its (now
    revoked) token — a user-revoked token carries no replacement, so
    presenting it is a plain failure with no family-wide side effect."""
    device_one = service.issue_refresh_token(db, user_a)
    device_two = service.issue_refresh_token(db, user_a)
    # Device two logs out; its stale tab/app then retries the old token.
    service.revoke_refresh_token(db, device_two)
    assert service.rotate_refresh_token(db, device_two) is None
    # Device one's session is untouched and still rotates fine.
    rotated = service.rotate_refresh_token(db, device_one)
    assert rotated is not None
    user, _ = rotated
    assert user.id == user_a.id
    assert _stored(db, device_two).replaced_by_id is None


def test_session_revoke_then_retry_keeps_the_kept_session(db, user_a):
    """Deep audit F4-01, Settings shape: "sign out other sessions"
    revokes the others; when a revoked device retries, the session
    the user KEPT must survive (it died under the old semantics)."""
    kept = service.issue_refresh_token(db, user_a)
    other = service.issue_refresh_token(db, user_a)
    ended = service.revoke_other_sessions(db, user_a, kept)
    assert ended == 1
    # The revoked device retries its token — plain 401, no fallout.
    assert service.rotate_refresh_token(db, other) is None
    rotated = service.rotate_refresh_token(db, kept)
    assert rotated is not None


def test_rotated_token_replay_still_kills_the_family(db, user_a):
    """Deep audit F4-01, theft direction: replaying a token that was
    ROTATED AWAY (replaced_by_id set) keeps the family-revoke
    response — including killing a second, untouched session."""
    first = service.issue_refresh_token(db, user_a)
    _, second = service.rotate_refresh_token(db, first)
    bystander = service.issue_refresh_token(db, user_a)
    assert service.rotate_refresh_token(db, first) is None  # replay
    assert service.rotate_refresh_token(db, second) is None
    assert service.rotate_refresh_token(db, bystander) is None
    assert _stored(db, second).revoked_at is not None
    assert _stored(db, bystander).revoked_at is not None
