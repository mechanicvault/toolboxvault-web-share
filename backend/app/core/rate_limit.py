"""Rate limiting (brute-force protection, blueprint §11).

Universal infrastructure: a tiny sliding-window counter of *failed*
login attempts, keyed by (client IP, account email). A successful
login clears the key.

Sheet row 115: the deployed limiters count in the
DATABASE (DbRateLimiter below), not in process memory — the API
runs two uvicorn workers, and per-process counters made every
budget twice as loose and every lockout worker-dependent. The
original in-process LoginRateLimiter stays as the reference
implementation: its unit tests pin the window semantics both
classes share. Timestamps in the database are wall-clock epoch
seconds — monotonic clocks are per-process and meaningless
across workers.

The visitor's address comes from client_ip() below, the ONE
reader every limiter key is built with: CF-Connecting-IP first
(Cloudflare writes it and a visitor cannot forge it through
Cloudflare), then the first X-Forwarded-For entry, then the
direct peer. The server also runs uvicorn with --proxy-headers
(backend/Dockerfile) so request.client agrees.
"""

import threading
import time
from collections import deque
from math import ceil

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.db import Base


def client_ip(request: Request) -> str:
    """The visitor's address as Cloudflare reports it; empty
    string when nothing usable rides the request. (Moved here
    from the teaser module, sheet row 115 — one reader,
    used consistently by every limiter key and the teaser
    exclusion alike.)"""
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


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


class RateLimitEvent(Base):
    """One counted attempt against a limiter key (row 115).

    A row per hit inside the window; rows older than their
    limiter's window are pruned on the next write for that
    key, so the table stays the size of live traffic, not
    history.
    """

    __tablename__ = "rate_limit_events"
    __table_args__ = (
        sa.Index("ix_rate_limit_events_key_ts", "key", "ts"),
    )

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    key = sa.Column(sa.String(255), nullable=False)
    ts = sa.Column(sa.Float, nullable=False)


class DbRateLimiter:
    """The LoginRateLimiter window semantics, counted in the
    database so every API worker shares one budget (row 115).

    Call sites pass their request session; the limiter works
    through a SIDE session bound to the same engine and
    commits there, so its rows persist whatever the request's
    own outcome (a failed login raises — the failure must
    still count) and never entangle the caller's transaction.
    `clock` is wall time (time.time): the stored timestamps
    have to mean the same thing in every process.
    """

    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        clock=time.time,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._clock = clock

    def _side_session(self, db: Session) -> Session:
        return sessionmaker(bind=db.get_bind(), expire_on_commit=False)()

    def retry_after(self, db: Session, key: str) -> int | None:
        """Seconds until the caller may try again, or None if allowed."""
        now = self._clock()
        side = self._side_session(db)
        try:
            attempts = list(
                side.execute(
                    sa.select(RateLimitEvent.ts)
                    .where(
                        RateLimitEvent.key == key,
                        RateLimitEvent.ts > now - self.window_seconds,
                    )
                    .order_by(RateLimitEvent.ts)
                ).scalars().all()
            )
            if len(attempts) >= self.max_attempts:
                return max(1, ceil(self.window_seconds - (now - attempts[0])))
            return None
        finally:
            side.close()

    def record_failure(self, db: Session, key: str) -> None:
        now = self._clock()
        side = self._side_session(db)
        try:
            side.execute(
                sa.delete(RateLimitEvent).where(
                    RateLimitEvent.key == key,
                    RateLimitEvent.ts <= now - self.window_seconds,
                )
            )
            side.add(RateLimitEvent(key=key, ts=now))
            side.commit()
        finally:
            side.close()

    def record_hit(self, db: Session, key: str) -> None:
        """Count one attempt against the budget (the
        request-budget reading — see LoginRateLimiter)."""
        self.record_failure(db, key)

    def record_success(self, db: Session, key: str) -> None:
        side = self._side_session(db)
        try:
            side.execute(
                sa.delete(RateLimitEvent).where(RateLimitEvent.key == key)
            )
            side.commit()
        finally:
            side.close()

    def clear_all(self, db: Session) -> None:
        """Drop every counted attempt (operator/test seam)."""
        side = self._side_session(db)
        try:
            side.execute(sa.delete(RateLimitEvent))
            side.commit()
        finally:
            side.close()


login_rate_limiter = DbRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)

# The unauthenticated email-sending doors (password-reset request,
# verification resend): a REQUEST budget, not a failure budget —
# handlers call record_hit for every request. Keys are per
# (IP, email) and per email alone, so one address can't be flooded
# from many IPs and one IP can't flood many addresses unchecked.
password_reset_rate_limiter = DbRateLimiter(
    max_attempts=settings.password_reset_rate_limit_attempts,
    window_seconds=settings.password_reset_rate_limit_window_seconds,
)

# The teaser signup gate's code door: a FAILURE
# budget per client IP, the login limiter's exact shape — five
# wrong codes inside a minute and the door pauses. The code is
# short, so this limiter is what makes guessing it impractical.
signup_unlock_rate_limiter = DbRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)

# Agent-code entry: the same
# FAILURE budget shape, keyed per IP + entering account in the
# dealers routes. A code is a capability — the owner hands it to
# one person — and wrong guesses must stay impractical, while a
# legitimate typo or two never locks the real agent out for long.
agent_code_rate_limiter = DbRateLimiter(
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
tier_conversion_rate_limiter = DbRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)

# The "Email this file" action:
# an authenticated, owner-scoped send — a modest REQUEST budget per
# user (10/hour) keeps a compromised session from turning the seam
# into a mail cannon. Handlers call record_hit per send.
attachment_email_rate_limiter = DbRateLimiter(
    max_attempts=10,
    window_seconds=3600,
)

# Manual lookup searches: every search fans out to
# public search engines and document hosts, so a REQUEST budget
# per user (30/hour) keeps one session from turning the site into
# a scraping cannon while leaving real use untouched. Handlers
# call record_hit per search.
manual_lookup_rate_limiter = DbRateLimiter(
    max_attempts=30,
    window_seconds=3600,
)

# Username availability checks: the signup
# and picker screens ask "is this name free?" as the user types.
# A REQUEST budget per client IP (60/minute) keeps the door from
# becoming a name-enumeration cannon while leaving typing-speed
# checks untouched. Handlers call record_hit per check.
username_check_rate_limiter = DbRateLimiter(
    max_attempts=60,
    window_seconds=60,
)
