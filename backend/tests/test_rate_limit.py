"""Login rate limiter (audit I1): sliding window over FAILED attempts,
per (IP, account) key. A fake clock drives the window — no sleeping.
"""

from app.core.rate_limit import LoginRateLimiter

KEY = "203.0.113.9:mechanic@example.com"


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _limiter(clock) -> LoginRateLimiter:
    return LoginRateLimiter(max_attempts=5, window_seconds=60, clock=clock)


def test_allows_attempts_below_the_limit():
    limiter = _limiter(_FakeClock())
    for _ in range(4):
        limiter.record_failure(KEY)
    assert limiter.retry_after(KEY) is None


def test_blocks_at_the_limit_with_a_retry_after():
    limiter = _limiter(_FakeClock())
    for _ in range(5):
        limiter.record_failure(KEY)
    retry = limiter.retry_after(KEY)
    assert retry is not None
    assert 1 <= retry <= 60


def test_window_expiry_allows_attempts_again():
    clock = _FakeClock()
    limiter = _limiter(clock)
    for _ in range(5):
        limiter.record_failure(KEY)
    assert limiter.retry_after(KEY) is not None
    clock.advance(61)
    assert limiter.retry_after(KEY) is None


def test_success_clears_the_counter():
    limiter = _limiter(_FakeClock())
    for _ in range(5):
        limiter.record_failure(KEY)
    limiter.record_success(KEY)
    assert limiter.retry_after(KEY) is None


def test_keys_are_independent():
    limiter = _limiter(_FakeClock())
    for _ in range(5):
        limiter.record_failure(KEY)
    other = "198.51.100.2:mechanic@example.com"
    assert limiter.retry_after(other) is None
    same_ip_other_account = "203.0.113.9:other@example.com"
    assert limiter.retry_after(same_ip_other_account) is None


# --- DbRateLimiter (sheet row 115): the same window semantics,
# counted in a database table so every API worker shares one
# budget. Each test drives its own in-memory SQLite factory,
# and a SECOND limiter instance over the same factory stands
# in for the second worker process.

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.rate_limit import DbRateLimiter, RateLimitEvent


def _db_factory():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[RateLimitEvent.__table__])
    return sessionmaker(bind=engine)


def _db_limiter(clock) -> DbRateLimiter:
    return DbRateLimiter(max_attempts=5, window_seconds=60, clock=clock)


def test_db_limiter_blocks_at_the_limit_and_expires():
    clock = _FakeClock()
    factory = _db_factory()
    db = factory()
    limiter = _db_limiter(clock)
    for _ in range(4):
        limiter.record_failure(db, KEY)
    assert limiter.retry_after(db, KEY) is None
    limiter.record_failure(db, KEY)
    retry = limiter.retry_after(db, KEY)
    assert retry is not None and 1 <= retry <= 60
    clock.advance(61)
    assert limiter.retry_after(db, KEY) is None


def test_db_limiter_counts_are_shared_across_instances():
    # The row 115 defect in miniature: two processes (two
    # limiter instances) must see ONE budget, not two.
    clock = _FakeClock()
    factory = _db_factory()
    db_a, db_b = factory(), factory()
    worker_a = _db_limiter(clock)
    worker_b = _db_limiter(clock)
    for _ in range(3):
        worker_a.record_failure(db_a, KEY)
    for _ in range(2):
        worker_b.record_failure(db_b, KEY)
    assert worker_a.retry_after(db_a, KEY) is not None
    assert worker_b.retry_after(db_b, KEY) is not None


def test_db_limiter_success_clears_and_keys_stay_independent():
    clock = _FakeClock()
    factory = _db_factory()
    db = factory()
    limiter = _db_limiter(clock)
    for _ in range(5):
        limiter.record_failure(db, KEY)
    assert limiter.retry_after(db, "198.51.100.2:mechanic@example.com") is None
    limiter.record_success(db, KEY)
    assert limiter.retry_after(db, KEY) is None
