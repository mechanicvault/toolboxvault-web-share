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
