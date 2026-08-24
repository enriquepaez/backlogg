"""Tests for TMDBSeriesClient's retry/backoff and timeout behaviour (Issue 7).

Covers:
- get_series_detail retries on a transient 5xx and succeeds on a later attempt
- get_series_detail returns None immediately on 404 — no retry
- get_series_credits retries on 429 and succeeds on a later attempt
- get_series_credits raises after exhausting retries on a persistent 5xx
- a non-retryable 4xx (e.g. 400) raises immediately without retrying
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backlogg.series.adapters.tmdb import TMDBSeriesClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    """Build a lightweight mock that mimics an httpx.Response."""
    response = MagicMock()
    response.status_code = status_code
    if json_data is not None:
        response.json = MagicMock(return_value=json_data)
    if status_code >= 400:
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"HTTP {status_code}", request=MagicMock(), response=response
            )
        )
    else:
        response.raise_for_status = MagicMock()
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_series_detail_retries_on_5xx_then_succeeds():
    """A transient 502 must be retried; the second attempt's 200 is returned."""
    detail = {"id": 84, "name": "Retry Test Series"}
    call_count = 0

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_response(502)
        return _mock_response(200, detail)

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        client = TMDBSeriesClient()
        result = await client.get_series_detail(84)

    assert result == detail
    assert call_count == 2


@pytest.mark.asyncio
async def test_get_series_detail_404_does_not_retry():
    """A 404 must return None immediately — no retry, no exception."""
    call_count = 0

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        return _mock_response(404)

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        client = TMDBSeriesClient()
        result = await client.get_series_detail(84)

    assert result is None
    assert call_count == 1
    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_series_credits_retries_on_429_then_succeeds():
    """A 429 (rate limit) must be retried; a later 200 attempt is returned."""
    credits_data = {"cast": [{"id": 1, "name": "Actor One"}], "crew": []}
    call_count = 0

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return _mock_response(429)
        return _mock_response(200, credits_data)

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        client = TMDBSeriesClient()
        result = await client.get_series_credits(84)

    assert result == credits_data
    assert call_count == 3
    assert mock_sleep.await_count == 2  # one backoff between each of the 3 attempts


@pytest.mark.asyncio
async def test_get_series_credits_raises_after_exhausting_retries():
    """A 503 that survives all 3 attempts must raise, never mask as success."""
    call_count = 0

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        return _mock_response(503)

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        client = TMDBSeriesClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_series_credits(84)

    assert call_count == 3


@pytest.mark.asyncio
async def test_search_series_returns_full_results_list():
    """search_series returns the whole page of results, not just the top hit (Issue #14)."""
    payload = {"page": 1, "results": [{"id": 1}, {"id": 2}], "total_pages": 1}
    captured: dict = {}

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        captured["params"] = kwargs.get("params")
        return _mock_response(200, payload)

    with patch("httpx.AsyncClient.get", new=fake_get):
        client = TMDBSeriesClient()
        results = await client.search_series("spiderman")

    assert results == [{"id": 1}, {"id": 2}]
    assert captured["params"]["page"] == 1


@pytest.mark.asyncio
async def test_search_series_returns_empty_list_when_no_matches():
    """search_series returns [] (not None) when TMDB has no matches."""

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        return _mock_response(200, {"page": 1, "results": [], "total_pages": 1})

    with patch("httpx.AsyncClient.get", new=fake_get):
        client = TMDBSeriesClient()
        results = await client.search_series("xxxxxxxxxxxxxxxxxxx_no_match")

    assert results == []


@pytest.mark.asyncio
async def test_search_series_forwards_page_param():
    """search_series forwards an explicit page to TMDB's native pagination."""
    captured: dict = {}

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        captured["params"] = kwargs.get("params")
        return _mock_response(200, {"page": 2, "results": [{"id": 55}], "total_pages": 5})

    with patch("httpx.AsyncClient.get", new=fake_get):
        client = TMDBSeriesClient()
        results = await client.search_series("spiderman", page=2)

    assert results == [{"id": 55}]
    assert captured["params"]["page"] == 2


@pytest.mark.asyncio
async def test_get_series_detail_non_retryable_4xx_raises_immediately():
    """A non-404 4xx (e.g. 401) is not transient — it must raise without retry."""
    call_count = 0

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        return _mock_response(401)

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        client = TMDBSeriesClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_series_detail(84)

    assert call_count == 1
    mock_sleep.assert_not_awaited()
