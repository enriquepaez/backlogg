"""Tests for TMDBClient's retry/backoff and timeout behaviour (Issue 7).

Covers:
- get_movie_detail retries on a transient 5xx and succeeds on a later attempt
- get_movie_detail returns None immediately on 404 — no retry
- get_movie_credits retries on 429 and succeeds on a later attempt
- get_movie_credits raises after exhausting retries on a persistent 5xx
- a non-retryable 4xx (e.g. 400) raises immediately without retrying
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backlogg.movies.adapters.tmdb import TMDBClient

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
async def test_get_movie_detail_retries_on_5xx_then_succeeds():
    """A transient 500 must be retried; the second attempt's 200 is returned."""
    detail = {"id": 42, "title": "Retry Test Movie"}
    call_count = 0

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_response(500)
        return _mock_response(200, detail)

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        client = TMDBClient()
        result = await client.get_movie_detail(42)

    assert result == detail
    assert call_count == 2


@pytest.mark.asyncio
async def test_get_movie_detail_404_does_not_retry():
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
        client = TMDBClient()
        result = await client.get_movie_detail(42)

    assert result is None
    assert call_count == 1
    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_movie_credits_retries_on_429_then_succeeds():
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
        client = TMDBClient()
        result = await client.get_movie_credits(42)

    assert result == credits_data
    assert call_count == 3
    assert mock_sleep.await_count == 2  # one backoff between each of the 3 attempts


@pytest.mark.asyncio
async def test_get_movie_credits_raises_after_exhausting_retries():
    """A 500 that survives all 3 attempts must raise, never mask as success."""
    call_count = 0

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        return _mock_response(500)

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        client = TMDBClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_movie_credits(42)

    assert call_count == 3


@pytest.mark.asyncio
async def test_search_movie_returns_full_results_list():
    """search_movie returns the whole page of results, not just the top hit (Issue #14)."""
    payload = {
        "page": 1,
        "results": [{"id": 1}, {"id": 2}, {"id": 3}],
        "total_pages": 1,
    }
    captured: dict = {}

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        captured["params"] = kwargs.get("params")
        return _mock_response(200, payload)

    with patch("httpx.AsyncClient.get", new=fake_get):
        client = TMDBClient()
        results = await client.search_movie("spiderman")

    assert results == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert captured["params"]["page"] == 1


@pytest.mark.asyncio
async def test_search_movie_returns_empty_list_when_no_matches():
    """search_movie returns [] (not None) when TMDB has no matches."""

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        return _mock_response(200, {"page": 1, "results": [], "total_pages": 1})

    with patch("httpx.AsyncClient.get", new=fake_get):
        client = TMDBClient()
        results = await client.search_movie("xxxxxxxxxxxxxxxxxxx_no_match")

    assert results == []


@pytest.mark.asyncio
async def test_search_movie_forwards_page_param():
    """search_movie forwards an explicit page to TMDB's native pagination."""
    captured: dict = {}

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        captured["params"] = kwargs.get("params")
        return _mock_response(200, {"page": 3, "results": [{"id": 99}], "total_pages": 5})

    with patch("httpx.AsyncClient.get", new=fake_get):
        client = TMDBClient()
        results = await client.search_movie("spiderman", page=3)

    assert results == [{"id": 99}]
    assert captured["params"]["page"] == 3


@pytest.mark.asyncio
async def test_get_movie_detail_non_retryable_4xx_raises_immediately():
    """A non-404 4xx (e.g. 400) is not transient — it must raise without retry."""
    call_count = 0

    async def fake_get(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        return _mock_response(400)

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        client = TMDBClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_movie_detail(42)

    assert call_count == 1
    mock_sleep.assert_not_awaited()
