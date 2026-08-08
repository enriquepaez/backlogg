"""Rate limiting — in-process sliding-window limiter behind a swappable interface.

The limiter counter lives behind the :class:`RateLimiter` abstract interface so
the in-process implementation can be replaced by a shared backend (e.g. Redis)
later **without touching any call site**: every consumer goes through
:func:`get_rate_limiter`, never the concrete class.

The default :class:`InMemoryRateLimiter` is a sliding-window-log limiter (a deque
of hit timestamps per key). It is sufficient for a single Render instance; a
distributed deployment would swap the factory for a Redis-backed implementation.

Error responses never leak the client IP, the configured limits, or any other
internal state — only a generic "Too many requests" message plus a
``Retry-After`` header.
"""

import math
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Callable
from typing import NamedTuple

from fastapi import HTTPException, Request

from backlogg.core.config import settings


class RateLimitResult(NamedTuple):
    """Outcome of consuming one hit against a limit."""

    allowed: bool
    retry_after: int


class RateLimiter(ABC):
    """Abstract rate limiter. Call sites depend only on this interface."""

    @abstractmethod
    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Consume one hit for *key* and report whether it is allowed.

        Returns a :class:`RateLimitResult`; when ``allowed`` is False,
        ``retry_after`` is the number of seconds the caller should wait before
        the oldest hit leaves the window.
        """
        raise NotImplementedError


class InMemoryRateLimiter(RateLimiter):
    """Sliding-window-log limiter backed by an in-process dict of deques.

    The clock is injectable (``now``) so tests can advance time deterministically
    without ``time.sleep``. State is process-local and lost on restart.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = self._now()
        window_start = now - window_seconds
        hits = self._hits[key]

        # Drop timestamps that have slid out of the window.
        while hits and hits[0] <= window_start:
            hits.popleft()

        if len(hits) >= limit:
            # The oldest in-window hit dictates when a slot frees up.
            retry_after = max(1, math.ceil(hits[0] + window_seconds - now))
            return RateLimitResult(allowed=False, retry_after=retry_after)

        hits.append(now)
        return RateLimitResult(allowed=True, retry_after=0)

    def reset(self) -> None:
        """Clear all recorded state (used by the test fixture between tests)."""
        self._hits.clear()


def parse_rate(spec: str) -> tuple[int, int]:
    """Parse a rate spec ``"count/seconds"`` into ``(limit, window_seconds)``.

    Raises:
        ValueError: if *spec* is not of the form ``<int>/<int>`` with both
            values positive.
    """
    parts = spec.split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid rate spec: {spec!r} (expected 'count/seconds')")
    try:
        limit = int(parts[0])
        window = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"Invalid rate spec: {spec!r} (expected 'count/seconds')") from exc
    if limit <= 0 or window <= 0:
        raise ValueError(f"Invalid rate spec: {spec!r} (count and seconds must be positive)")
    return limit, window


# ── Singleton factory ─────────────────────────────────────────────────────────
#
# Built once at import time. Call sites use get_rate_limiter() exclusively so the
# backing implementation can be swapped here alone (e.g. Redis) without changes
# elsewhere.
_rate_limiter: RateLimiter = InMemoryRateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Return the process-wide rate limiter instance."""
    return _rate_limiter


def client_ip(request: Request) -> str:
    """Best-effort client IP.

    Render sits behind a proxy, so prefer the first hop of ``X-Forwarded-For``.
    Fall back to the direct peer, then to ``"unknown"``.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def _raise_rate_limited(retry_after: int) -> None:
    """Raise a generic 429 that never leaks IP, limits, or other internal state."""
    raise HTTPException(
        status_code=429,
        detail="Too many requests. Please try again later.",
        headers={"Retry-After": str(retry_after)},
    )


async def rate_limit_auth(request: Request) -> None:
    """FastAPI dependency: rate limit auth endpoints per client IP.

    Consumes one hit from the ``RATE_LIMIT_AUTH`` bucket keyed by IP and raises a
    generic 429 with ``Retry-After`` when the limit is exceeded.
    """
    ip = client_ip(request)
    limit, window = parse_rate(settings.RATE_LIMIT_AUTH)
    result = get_rate_limiter().check(f"auth:{ip}", limit, window)
    if not result.allowed:
        _raise_rate_limited(result.retry_after)


def enforce_search_fallback(ip: str) -> None:
    """Rate limit the external search fan-out per client IP.

    Consumes one hit from the ``RATE_LIMIT_SEARCH_FALLBACK`` bucket keyed by IP
    and raises a generic 429 (before any external API call) when exceeded.
    """
    limit, window = parse_rate(settings.RATE_LIMIT_SEARCH_FALLBACK)
    result = get_rate_limiter().check(f"search_fallback:{ip}", limit, window)
    if not result.allowed:
        _raise_rate_limited(result.retry_after)
