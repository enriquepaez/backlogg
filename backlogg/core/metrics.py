"""Metrics — stdlib-only Prometheus exposition registry.

Platform-layer sibling of ``core/observability.py`` and ``core/rate_limit.py``.
No third-party dependency (no ``prometheus-client``): the Prometheus text
exposition format (version ``0.0.4``) is serialised by hand from an in-process,
thread-safe registry. This is consistent with the JSON-logging (feature 38) and
SMTP (feature 36) stdlib-only precedents.

Exposed metric families:

* ``http_requests_total`` — counter, labels ``method`` / ``path`` / ``status``.
* ``http_request_duration_seconds`` — histogram, labels ``method`` / ``path``,
  with cumulative ``_bucket{le=...}`` series plus ``_sum`` and ``_count``.
* ``backlogg_syncs_total`` — counter, label ``type`` (sync jobs executed).
* ``backlogg_external_fanout_total`` — counter, label ``source`` (external API
  fan-outs during the /search fallback).

**Cardinality & PII safety.** The ``path`` label is always the *route template*
(``/movies/{slug}``, ``/users/{username}``), never the concrete URL
(``/movies/dune-2021``). This keeps the series count bounded and, crucially,
keeps user identifiers, slugs, query strings and headers out of the metrics.
See :class:`MetricsMiddleware` for how the template is resolved.

The registry is guarded by a single :class:`threading.Lock` around all mutable
state, so instrumentation is safe under the threadpool the ASGI server uses and
the observe/increment paths stay O(1).
"""

import threading
import time
from collections.abc import Callable, Sequence

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# The exact content type Prometheus scrapers expect for the text format v0.0.4.
CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

# The endpoint that serves the exposition. Excluded from its own instrumentation.
METRICS_PATH = "/metrics"

# Default latency buckets (seconds). Mirrors the well-known Prometheus client
# default so downstream dashboards/queries behave as operators expect.
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

# Sentinel used when a request does not resolve to a route (e.g. a 404 for an
# unknown URL). Using one fixed bucket instead of the raw URL prevents an
# unbounded explosion of series driven by arbitrary/hostile paths.
UNMATCHED_PATH = "__unmatched__"

_LabelKey = tuple[tuple[str, str], ...]


def _escape_label_value(value: str) -> str:
    """Escape a label value per the exposition format (backslash, quote, newline)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(labels: _LabelKey) -> str:
    """Render a label key as ``{k="v",...}`` (empty string when there are none)."""
    if not labels:
        return ""
    inner = ",".join(f'{key}="{_escape_label_value(value)}"' for key, value in labels)
    return "{" + inner + "}"


def _format_number(value: float) -> str:
    """Render a numeric sample: whole numbers without a decimal point."""
    if value == int(value):
        return str(int(value))
    return repr(value)


def _format_bucket(bound: float) -> str:
    """Render a bucket upper bound for the ``le`` label."""
    if bound == int(bound):
        return str(int(bound))
    return repr(bound)


class _HistogramValue:
    """Per-labelset histogram state: cumulative bucket counts, sum and count.

    ``buckets[i]`` counts observations ``<= bounds[i]``. Because every
    observation increments *each* bucket whose bound it satisfies, the counts
    are naturally monotonic non-decreasing across ascending bounds — exactly the
    cumulative semantics Prometheus histograms require. ``count`` doubles as the
    implicit ``+Inf`` bucket.
    """

    __slots__ = ("bounds", "counts", "sum", "count")

    def __init__(self, bounds: tuple[float, ...]) -> None:
        self.bounds = bounds
        self.counts = [0] * len(bounds)
        self.sum = 0.0
        self.count = 0

    def observe(self, value: float) -> None:
        self.count += 1
        self.sum += value
        for i, bound in enumerate(self.bounds):
            if value <= bound:
                self.counts[i] += 1


class MetricsRegistry:
    """In-process, thread-safe registry that renders Prometheus exposition text.

    Metric families are pre-registered in :meth:`__init__` so their ``# HELP`` /
    ``# TYPE`` lines are always present in the output, even before the first
    observation. Call sites only ever go through :meth:`inc_counter` and
    :meth:`observe`; the exposition is produced by :meth:`render`.
    """

    def __init__(self, buckets: Sequence[float] = DEFAULT_BUCKETS) -> None:
        self._lock = threading.Lock()
        self._buckets: tuple[float, ...] = tuple(sorted(buckets))
        self._help: dict[str, str] = {}
        self._types: dict[str, str] = {}
        self._counters: dict[str, dict[_LabelKey, float]] = {}
        self._histograms: dict[str, dict[_LabelKey, _HistogramValue]] = {}

        self._register_counter(
            "http_requests_total",
            "Total HTTP requests by method, route template and status.",
        )
        self._register_counter(
            "backlogg_syncs_total",
            "Total content sync jobs executed, by content type.",
        )
        self._register_counter(
            "backlogg_external_fanout_total",
            "Total external API fan-outs during the search fallback, by source.",
        )
        self._register_histogram(
            "http_request_duration_seconds",
            "HTTP request latency in seconds by method and route template.",
        )

    # ── registration ────────────────────────────────────────────────────────
    def _register_counter(self, name: str, help_text: str) -> None:
        self._help[name] = help_text
        self._types[name] = "counter"
        self._counters[name] = {}

    def _register_histogram(self, name: str, help_text: str) -> None:
        self._help[name] = help_text
        self._types[name] = "histogram"
        self._histograms[name] = {}

    @staticmethod
    def _key(labels: dict[str, str] | None) -> _LabelKey:
        if not labels:
            return ()
        return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

    # ── mutation ────────────────────────────────────────────────────────────
    def inc_counter(
        self, name: str, labels: dict[str, str] | None = None, amount: float = 1.0
    ) -> None:
        """Increment counter *name* for the given label set (default +1)."""
        key = self._key(labels)
        with self._lock:
            family = self._counters[name]
            family[key] = family.get(key, 0.0) + amount

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record one observation *value* into histogram *name* for the label set."""
        key = self._key(labels)
        with self._lock:
            family = self._histograms[name]
            hist = family.get(key)
            if hist is None:
                hist = _HistogramValue(self._buckets)
                family[key] = hist
            hist.observe(value)

    def reset(self) -> None:
        """Clear all recorded samples (used by the test fixture between tests)."""
        with self._lock:
            for family in self._counters.values():
                family.clear()
            for family in self._histograms.values():
                family.clear()

    # ── rendering ───────────────────────────────────────────────────────────
    def render(self) -> str:
        """Serialise the whole registry as Prometheus exposition text."""
        lines: list[str] = []
        with self._lock:
            for name in self._counters:
                lines.extend(self._render_counter(name))
            for name in self._histograms:
                lines.extend(self._render_histogram(name))
        return "\n".join(lines) + "\n"

    def _render_counter(self, name: str) -> list[str]:
        lines = [f"# HELP {name} {self._help[name]}", f"# TYPE {name} counter"]
        family = self._counters[name]
        for key in sorted(family):
            lines.append(f"{name}{_format_labels(key)} {_format_number(family[key])}")
        return lines

    def _render_histogram(self, name: str) -> list[str]:
        lines = [f"# HELP {name} {self._help[name]}", f"# TYPE {name} histogram"]
        family = self._histograms[name]
        for key in sorted(family):
            hist = family[key]
            for bound, cumulative in zip(hist.bounds, hist.counts, strict=True):
                bucket_key = (*key, ("le", _format_bucket(bound)))
                lines.append(f"{name}_bucket{_format_labels(bucket_key)} {cumulative}")
            inf_key = (*key, ("le", "+Inf"))
            lines.append(f"{name}_bucket{_format_labels(inf_key)} {hist.count}")
            lines.append(f"{name}_sum{_format_labels(key)} {_format_number(hist.sum)}")
            lines.append(f"{name}_count{_format_labels(key)} {hist.count}")
        return lines


# ── Singleton factory ─────────────────────────────────────────────────────────
#
# Built once at import time. Call sites use get_metrics() exclusively so the
# backing implementation can be swapped here alone (e.g. a shared/remote backend)
# without changes elsewhere — same pattern as core/rate_limit.get_rate_limiter.
_metrics = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    """Return the process-wide metrics registry."""
    return _metrics


def _route_template(request: Request) -> str:
    """Return the matched route template, or a fixed sentinel for unmatched URLs.

    The template (``/movies/{slug}``) is used instead of the concrete URL
    (``/movies/dune-2021``) so slugs/usernames/ids never become labels. Starlette
    stores the matched route on the shared scope during downstream handling, so
    it is available once ``call_next`` has returned.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if path else UNMATCHED_PATH


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count and latency per (method, route template, status).

    The ``path`` label is always the route template, never the raw URL, so no
    identifier, query string or header value ever reaches the metrics. Unmatched
    requests are folded into a single :data:`UNMATCHED_PATH` bucket.

    ``/metrics`` is deliberately excluded from its own instrumentation: a scraper
    hitting it every few seconds would otherwise dominate the counters with
    self-referential noise that says nothing about real traffic.

    Recording happens in a ``finally`` block so a request that raises still
    contributes a sample (defaulting to status 500) before the exception
    continues propagating to the error handler.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            template = _route_template(request)
            if template != METRICS_PATH:
                labels = {"method": request.method, "path": template}
                registry = get_metrics()
                registry.observe("http_request_duration_seconds", duration, labels=labels)
                registry.inc_counter(
                    "http_requests_total",
                    labels={**labels, "status": str(status)},
                )
