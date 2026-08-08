"""In-process response cache behind a swappable interface.

The cache lives behind the :class:`Cache` abstract interface so the default
in-process implementation can be replaced by a shared backend (e.g. Redis)
later **without touching any call site**: every consumer goes through
:func:`get_cache`, never the concrete class. Same pattern as
``core/rate_limit.get_rate_limiter`` and ``core/email.get_email_sender``.

The default :class:`InMemoryTTLCache` stores each value with a per-entry expiry.
A value is served only while ``now() < expires_at``; an expired entry is evicted
lazily on the next read and treated as a miss, so a stale value can never
outlive its configured TTL. State is process-local and lost on restart, which is
fine for the hot, cheap-to-recompute reads it backs (``/trending``, ``/genres``).
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class Cache(ABC):
    """Abstract TTL cache. Call sites depend only on this interface."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Return the cached value for *key*, or ``None`` if absent or expired."""
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store *value* under *key* for *ttl_seconds* seconds."""
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """Drop all cached entries (used by the test fixture between tests)."""
        raise NotImplementedError


class InMemoryTTLCache(Cache):
    """Process-local cache with per-entry TTL and lazy expiry.

    The clock is injectable (``now``) so tests can advance time deterministically
    without ``time.sleep``. A value is returned only while ``now() < expires_at``;
    an expired entry is evicted on read and treated as a miss, so stale data is
    never served beyond its TTL.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._now() >= expires_at:
            # Lazily evict expired entries so stale data never outlives its TTL.
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._store[key] = (self._now() + ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()


# ── Singleton factory ─────────────────────────────────────────────────────────
#
# Built once at import time. Call sites use get_cache() exclusively so the
# backing implementation can be swapped here alone (e.g. Redis) without changes
# elsewhere — same pattern as get_rate_limiter / get_email_sender.
_cache: Cache = InMemoryTTLCache()


def get_cache() -> Cache:
    """Return the process-wide response cache instance."""
    return _cache
