"""Unit tests for the in-process rate limiter and rate spec parser."""

import pytest

from backlogg.core.rate_limit import (
    InMemoryRateLimiter,
    RateLimiter,
    get_rate_limiter,
    parse_rate,
)


class _FakeClock:
    """A mutable, injectable clock for deterministic time control."""

    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


# ── InMemoryRateLimiter ───────────────────────────────────────────────────────


def test_allows_up_to_the_limit():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(now=clock)
    for _ in range(3):
        result = limiter.check("k", limit=3, window_seconds=60)
        assert result.allowed is True
        assert result.retry_after == 0


def test_blocks_hit_beyond_the_limit():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(now=clock)
    for _ in range(3):
        limiter.check("k", limit=3, window_seconds=60)
    result = limiter.check("k", limit=3, window_seconds=60)
    assert result.allowed is False
    assert result.retry_after > 0


def test_retry_after_reflects_remaining_window():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(now=clock)
    # First (and only) hit at t=1000, window 60s.
    limiter.check("k", limit=1, window_seconds=60)
    clock.advance(20)  # 40s left until the oldest hit slides out
    result = limiter.check("k", limit=1, window_seconds=60)
    assert result.allowed is False
    assert result.retry_after == 40


def test_allows_again_after_window_passes():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(now=clock)
    for _ in range(2):
        assert limiter.check("k", limit=2, window_seconds=60).allowed is True
    # Third hit is blocked while the window is full.
    assert limiter.check("k", limit=2, window_seconds=60).allowed is False
    # Advance beyond the window: the old hits slide out and the key resets.
    clock.advance(61)
    assert limiter.check("k", limit=2, window_seconds=60).allowed is True


def test_keys_are_isolated():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(now=clock)
    assert limiter.check("a", limit=1, window_seconds=60).allowed is True
    # A different key has its own bucket.
    assert limiter.check("b", limit=1, window_seconds=60).allowed is True
    # The first key is now exhausted.
    assert limiter.check("a", limit=1, window_seconds=60).allowed is False


def test_reset_clears_all_state():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(now=clock)
    limiter.check("k", limit=1, window_seconds=60)
    assert limiter.check("k", limit=1, window_seconds=60).allowed is False
    limiter.reset()
    assert limiter.check("k", limit=1, window_seconds=60).allowed is True


def test_retry_after_minimum_is_one():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(now=clock)
    limiter.check("k", limit=1, window_seconds=1)
    # Same instant: window has 1s left, retry_after must round up to at least 1.
    result = limiter.check("k", limit=1, window_seconds=1)
    assert result.allowed is False
    assert result.retry_after >= 1


# ── get_rate_limiter (swappable interface) ────────────────────────────────────


def test_get_rate_limiter_returns_singleton_implementing_interface():
    a = get_rate_limiter()
    b = get_rate_limiter()
    assert a is b
    assert isinstance(a, RateLimiter)


# ── parse_rate ────────────────────────────────────────────────────────────────


def test_parse_rate_valid():
    assert parse_rate("10/60") == (10, 60)
    assert parse_rate("1/1") == (1, 1)
    assert parse_rate("120/60") == (120, 60)


@pytest.mark.parametrize(
    "spec",
    ["10", "10/", "/60", "10/60/1", "abc/60", "10/xyz", "0/60", "10/0", "-1/60", ""],
)
def test_parse_rate_invalid_raises_value_error(spec):
    with pytest.raises(ValueError):
        parse_rate(spec)
