"""Email-verification plumbing (audit I2): token minting, the send
seam, one-time consumption. Login gating (the
auth.require_email_verification launch switch) is covered in
test_email_flows.py with the rest of the email flows.
"""

from datetime import datetime, timedelta, timezone

from app.core import notifications
from app.core.security import generate_opaque_token
from app.modules.core import models, service


def _capture_link(monkeypatch) -> dict:
    captured = {}

    def fake_send(db, email: str, plain_token: str, locale: str = "en") -> bool:
        captured["email"] = email
        captured["token"] = plain_token
        return True

    monkeypatch.setattr(notifications, "send_verification_email", fake_send)
    return captured


def test_signup_verification_flow(db, user_a, monkeypatch):
    captured = _capture_link(monkeypatch)
    service.start_email_verification(db, user_a)
    assert captured["email"] == user_a.email
    assert user_a.email_verified is False

    assert service.verify_email(db, captured["token"]) is True
    db.refresh(user_a)
    assert user_a.email_verified is True


def test_verification_token_is_single_use(db, user_a, monkeypatch):
    captured = _capture_link(monkeypatch)
    service.start_email_verification(db, user_a)
    assert service.verify_email(db, captured["token"]) is True
    assert service.verify_email(db, captured["token"]) is False


def test_unknown_verification_token_is_rejected(db, user_a):
    assert service.verify_email(db, "no-such-token") is False


def test_expired_verification_token_is_rejected(db, user_a):
    plain, token_hash = generate_opaque_token()
    db.add(
        models.EmailVerificationToken(
            user_id=user_a.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db.commit()
    assert service.verify_email(db, plain) is False
    db.refresh(user_a)
    assert user_a.email_verified is False
