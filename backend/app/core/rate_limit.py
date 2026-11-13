"""In-process login rate limiting (brute-force protection, blueprint §11).

Universal infrastructure: a tiny sliding-window counter of *failed* login
attempts, keyed by (client IP, account email). A successful login clears
the key. State lives in process memory — correct for the single-API-
container deployment; revisit if the API is ever scaled horizontally.

No third-party dependency on purpose: this is ~40 lines and the window
semantics (failures only, per IP+account) are exactly what §11 asks for.
"""

import threading
import time
from collections import deque
from math import ceil

from app.core.config import settings


class LoginRateLimiter:
    """Sliding-window failed-attempt limiter.

    `clock` is injectable so tests can advance time without sleeping.
    """

    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        clock=time.monotonic,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        attempts = self._failures.setdefault(key, deque())
        while attempts and now - attempts[0] >= self.window_seconds:
            attempts.popleft()
        if not attempts:
            self._failures.pop(key, None)
        return attempts

    def retry_after(self, key: str) -> int | None:
        """Seconds until the caller may try again, or None if allowed."""
        now = self._clock()
        with self._lock:
            attempts = self._prune(key, now)
            if len(attempts) >= self.max_attempts:
                return max(1, ceil(self.window_seconds - (now - attempts[0])))
            return None

    def record_failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            attempts = self._prune(key, now)
            attempts.append(now)
            self._failures[key] = attempts

    def record_hit(self, key: str) -> None:
        """Count one attempt against the budget — the request-budget
        reading of the same counter (every request counts, not just
        failures). Used by the email-send limiter below."""
        self.record_failure(key)

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_rate_limiter = LoginRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)

# The unauthenticated email-sending doors (password-reset request,
# verification resend): a REQUEST budget, not a failure budget —
# handlers call record_hit for every request. Keys are per
# (IP, email) and per email alone, so one address can't be flooded
# from many IPs and one IP can't flood many addresses unchecked.
password_reset_rate_limiter = LoginRateLimiter(
    max_attempts=settings.password_reset_rate_limit_attempts,
    window_seconds=settings.password_reset_rate_limit_window_seconds,
)

# The teaser signup gate's code door (2026-10-26): a FAILURE
# budget per client IP, the login limiter's exact shape — five
# wrong codes inside a minute and the door pauses. The code is
# short, so this limiter is what makes guessing it impractical.
signup_unlock_rate_limiter = LoginRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)

# Agent-code entry (dealer takeover, 2026-11-03): the same
# FAILURE budget shape, keyed per IP + entering account in the
# dealers routes. A code is a capability — the owner hands it to
# one person — and wrong guesses must stay impractical, while a
# legitimate typo or two never locks the real agent out for long.
agent_code_rate_limiter = LoginRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)

# Tier-conversion code entry (downloads level → normal, owner
# order 2026-11-10): the SAME gate code the signup door checks,
# entered by an already-registered limited account. The signup
# door's limiter is keyed per client IP (its callers are
# anonymous); this door's callers are authenticated, so the
# FAILURE budget keys per ACCOUNT — one account's guesses can
# never pause another's door, and moving IPs doesn't reset the
# budget. Five wrong codes inside a minute pauses the door.
tier_conversion_rate_limiter = LoginRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)

# The "Email this file" action (item structure package, 2026-10-18):
# an authenticated, owner-scoped send — a modest REQUEST budget per
# user (10/hour) keeps a compromised session from turning the seam
# into a mail cannon. Handlers call record_hit per send.
attachment_email_rate_limiter = LoginRateLimiter(
    max_attempts=10,
    window_seconds=3600,
)

# Manual lookup searches (2026-11-05): every search fans out to
# public search engines and document hosts, so a REQUEST budget
# per user (30/hour) keeps one session from turning the site into
# a scraping cannon while leaving real use untouched. Handlers
# call record_hit per search.
manual_lookup_rate_limiter = LoginRateLimiter(
    max_attempts=30,
    window_seconds=3600,
)
