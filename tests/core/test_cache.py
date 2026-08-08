"""Unit tests for the in-process TTL cache (feature 40).

The clock is injected so TTL expiry is exercised deterministically without
``time.sleep`` — the same pattern the rate limiter tests use.
"""

from backlogg.core.cache import Cache, InMemoryTTLCache, get_cache


class _FakeClock:
    """A manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_get_missing_key_returns_none():
    cache = InMemoryTTLCache(now=_FakeClock())
    assert cache.get("nope") is None


def test_set_then_get_hit_within_ttl():
    clock = _FakeClock()
    cache = InMemoryTTLCache(now=clock)

    cache.set("k", "v", ttl_seconds=10)
    assert cache.get("k") == "v"

    clock.advance(9)
    # Still inside the TTL window → hit.
    assert cache.get("k") == "v"


def test_value_expires_exactly_at_ttl_boundary():
    clock = _FakeClock()
    cache = InMemoryTTLCache(now=clock)

    cache.set("k", "v", ttl_seconds=10)
    clock.advance(10)
    # At the boundary the entry is already stale — never served past its TTL.
    assert cache.get("k") is None


def test_value_not_served_after_ttl():
    clock = _FakeClock()
    cache = InMemoryTTLCache(now=clock)

    cache.set("k", "first", ttl_seconds=5)
    clock.advance(6)
    assert cache.get("k") is None

    # A fresh write after expiry starts a new TTL window.
    cache.set("k", "second", ttl_seconds=5)
    assert cache.get("k") == "second"


def test_clear_drops_all_entries():
    cache = InMemoryTTLCache(now=_FakeClock())
    cache.set("a", 1, ttl_seconds=100)
    cache.set("b", 2, ttl_seconds=100)

    cache.clear()

    assert cache.get("a") is None
    assert cache.get("b") is None


def test_get_cache_returns_singleton_cache_instance():
    cache = get_cache()
    assert isinstance(cache, Cache)
    # Same process-wide instance on every call (swappable in one place).
    assert get_cache() is cache
