"""Tests for the metrics endpoint and registry (feature 39).

Acceptance criteria validated here:
  AC1  GET /metrics returns 200 in Prometheus exposition format (+ content type)
  AC2  Includes request totals by method+route+status and a latency histogram
       (cumulative _bucket{le=...}, _sum, _count)
  AC3  Includes business counters: syncs executed and external fan-outs
  AC4  No PII / sensitive data in labels — the route *template* is used, never
       the concrete URL, query strings or headers
  AC5  Instrumentation is bounded, thread-safe and does not break existing routes
  AC6  Tests verify the format and the presence of the key series
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backlogg.core.metrics import (
    CONTENT_TYPE_LATEST,
    DEFAULT_BUCKETS,
    MetricsRegistry,
    get_metrics,
)
from backlogg.main import app

client = TestClient(app)


# A throwaway *templated* route so the route-template label can be exercised
# without touching the DB. The path segment carries a would-be identifier that
# must never appear in the metrics (only the template should).
@app.get("/_test/echo/{item_id}")
async def _echo(item_id: str):
    return {"item_id": item_id}


# ── Exposition parsing helpers ─────────────────────────────────────────────────


def _parse_samples(text: str) -> dict[str, float]:
    """Parse ``metric{labels} value`` lines into a {full_series: value} dict.

    Ignores ``# HELP`` / ``# TYPE`` comment lines. The key is the verbatim
    ``name{labels}`` (or just ``name``) so tests can assert exact series.
    """
    samples: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        series, _, value = line.rpartition(" ")
        samples[series] = float(value)
    return samples


# ── Registry unit tests (AC2 histogram semantics, escaping) ─────────────────────


def test_counter_increments_and_renders():
    reg = MetricsRegistry()
    reg.inc_counter("http_requests_total", {"method": "GET", "path": "/x", "status": "200"})
    reg.inc_counter("http_requests_total", {"method": "GET", "path": "/x", "status": "200"})
    samples = _parse_samples(reg.render())
    assert samples['http_requests_total{method="GET",path="/x",status="200"}'] == 2


def test_histogram_buckets_are_cumulative_and_monotonic():
    reg = MetricsRegistry()
    for value in (0.003, 0.03, 0.3, 3.0):
        reg.observe("http_request_duration_seconds", value, {"method": "GET", "path": "/x"})
    text = reg.render()
    samples = _parse_samples(text)

    # Extract the ordered bucket counts for this labelset.
    bucket_counts = [
        samples[f'http_request_duration_seconds_bucket{{method="GET",path="/x",le="{_le(b)}"}}']
        for b in DEFAULT_BUCKETS
    ]
    # Cumulative → non-decreasing across ascending bounds.
    assert bucket_counts == sorted(bucket_counts)
    # The 0.005 bucket holds only the 0.003 observation.
    assert bucket_counts[0] == 1
    # +Inf and _count both equal the total number of observations.
    inf = samples['http_request_duration_seconds_bucket{method="GET",path="/x",le="+Inf"}']
    count = samples['http_request_duration_seconds_count{method="GET",path="/x"}']
    assert inf == count == 4
    # _sum equals the sum of the observed values.
    sum_ = samples['http_request_duration_seconds_sum{method="GET",path="/x"}']
    assert abs(sum_ - (0.003 + 0.03 + 0.3 + 3.0)) < 1e-9


def test_label_values_are_escaped():
    reg = MetricsRegistry()
    reg.inc_counter("http_requests_total", {"method": "GET", "path": 'a"b\\c', "status": "200"})
    rendered = reg.render()
    # The raw quote/backslash are escaped so the exposition stays parseable.
    assert 'path="a\\"b\\\\c"' in rendered


def test_help_and_type_lines_present_for_all_families():
    reg = MetricsRegistry()
    rendered = reg.render()
    for name, kind in (
        ("http_requests_total", "counter"),
        ("http_request_duration_seconds", "histogram"),
        ("backlogg_syncs_total", "counter"),
        ("backlogg_external_fanout_total", "counter"),
    ):
        assert f"# HELP {name} " in rendered
        assert f"# TYPE {name} {kind}" in rendered


def _le(bound: float) -> str:
    return str(int(bound)) if bound == int(bound) else repr(bound)


# ── Endpoint tests (AC1) ────────────────────────────────────────────────────────


def test_metrics_endpoint_returns_200_and_content_type():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"] == CONTENT_TYPE_LATEST


def test_metrics_endpoint_is_parseable_exposition():
    """AC1/AC6: the body parses as exposition and carries the known families."""
    body = client.get("/metrics").text
    assert "# HELP http_requests_total" in body
    assert "# TYPE http_request_duration_seconds histogram" in body
    # Every non-comment line must be a well-formed ``series value`` pair.
    samples = _parse_samples(body)
    assert isinstance(samples, dict)


# ── Request instrumentation (AC2, AC4, AC5) ─────────────────────────────────────


def test_requests_counted_by_method_route_and_status():
    get_metrics().reset()
    client.get("/health")
    client.get("/health")
    samples = _parse_samples(client.get("/metrics").text)
    assert samples['http_requests_total{method="GET",path="/health",status="200"}'] == 2


def test_latency_histogram_recorded_for_requests():
    get_metrics().reset()
    client.get("/health")
    samples = _parse_samples(client.get("/metrics").text)
    assert samples['http_request_duration_seconds_count{method="GET",path="/health"}'] == 1
    assert 'http_request_duration_seconds_bucket{method="GET",path="/health",le="+Inf"}' in samples
    assert 'http_request_duration_seconds_sum{method="GET",path="/health"}' in samples


def test_path_label_uses_route_template_not_raw_url():
    """AC4: the label carries the template, never the concrete identifier."""
    get_metrics().reset()
    response = client.get("/_test/echo/super-secret-id-42?token=leakme")
    assert response.status_code == 200
    body = client.get("/metrics").text
    # The template is present …
    assert 'path="/_test/echo/{item_id}"' in body
    # … and no concrete identifier, query string or query value leaked into it.
    assert "super-secret-id-42" not in body
    assert "leakme" not in body
    assert "token=" not in body


def test_unmatched_url_folds_into_single_bucket():
    """AC4: unknown URLs (404, no route) do not explode cardinality."""
    get_metrics().reset()
    client.get("/this-route-does-not-exist-zzz")
    body = client.get("/metrics").text
    assert 'path="__unmatched__"' in body
    assert "this-route-does-not-exist-zzz" not in body


def test_metrics_endpoint_excluded_from_its_own_instrumentation():
    get_metrics().reset()
    client.get("/metrics")
    body = client.get("/metrics").text
    assert 'path="/metrics"' not in body


def test_instrumentation_does_not_break_existing_endpoint():
    """AC5: an instrumented request still returns its normal response."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ── Business counters (AC3) ─────────────────────────────────────────────────────


def _mocked_session_factory():
    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_cm)


async def test_sync_job_increments_syncs_counter(monkeypatch):
    """AC3: running a sync job increments backlogg_syncs_total{type=...}."""
    from backlogg.scheduler import jobs as sync_jobs

    get_metrics().reset()
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_MOVIES", 10)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 3)

    with (
        patch("backlogg.scheduler.jobs.get_sync_offset", new_callable=AsyncMock, return_value=0),
        patch("backlogg.scheduler.jobs.set_sync_offset", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs._refresh_catalog_search", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory()),
        patch.object(
            sync_jobs._tmdb_movies,
            "get_top_movies",
            new_callable=AsyncMock,
            return_value=[{"id": None}],
        ),
    ):
        await sync_jobs.sync_movies()

    samples = _parse_samples(get_metrics().render())
    assert samples['backlogg_syncs_total{type="movie"}'] == 1


async def test_search_fanout_increments_external_counter():
    """AC3: an external ingest increments backlogg_external_fanout_total{source=...}."""
    from backlogg.search import service

    get_metrics().reset()
    with patch.object(
        service._tmdb_movies, "search_movie", new_callable=AsyncMock, return_value=[]
    ):
        await service._ingest_movies("some query", page=1, limit=20)

    samples = _parse_samples(get_metrics().render())
    assert samples['backlogg_external_fanout_total{source="movie"}'] == 1


def test_no_sensitive_values_appear_in_metrics(monkeypatch):
    """AC4: a request carrying secrets in header/query must not leak into labels."""
    get_metrics().reset()
    client.get(
        "/_test/echo/abc?password=hunter2&api_key=sk-leak",
        headers={"Authorization": "Bearer tok-leak", "X-API-Key": "admin-leak"},
    )
    body = client.get("/metrics").text
    for secret in ("hunter2", "sk-leak", "tok-leak", "admin-leak", "password", "api_key"):
        assert secret not in body
