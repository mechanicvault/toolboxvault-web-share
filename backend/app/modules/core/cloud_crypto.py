"""Field encryption for secrets stored in the database (wave 4).

The app had no field-encryption helper before cloud backups:
users' Google Drive refresh tokens must sit in the DB (the
scheduler needs them while the user is away), and a refresh
token is a long-lived credential — it is never stored in
plaintext.

Scheme: Fernet (AES-128-CBC + HMAC) from the `cryptography`
package. Key sources, in order:
  1. The TOKEN_ENCRYPTION_KEY setting (a Fernet key: urlsafe
     base64 of 32 bytes) — the production posture.
  2. DERIVED from the JWT secret (SHA-256, base64) when no
     dedicated key is set. Documented trade-off: rotating the
     JWT secret then strands stored tokens — affected users
     simply reconnect (the failure mode is a failed backup +
     an inbox notice, never silent data loss). Operators are
     told to set the dedicated key; the derivation exists so the
     feature is safe-by-default rather than blocked on config.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    configured = (settings.token_encryption_key or "").strip()
    if configured:
        return Fernet(configured.encode())
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt one secret for storage (returns the token text)."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a stored secret. Raises ValueError when the token
    can't be opened (wrong/rotated key, corruption)."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise ValueError("Stored secret could not be decrypted.") from exc
