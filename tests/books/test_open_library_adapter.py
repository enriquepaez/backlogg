"""Tests for the OpenLibraryClient adapter.

Covers:
- User-Agent header is sent in get_trending_books requests
- get_trending_books returns [] when the API responds with 403
- get_trending_books correctly parses a response containing a non-empty "works" list
- get_author retries on TimeoutException and returns None after 3 failures
- get_author succeeds on a retry after an initial timeout
- get_author returns None on 404
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backlogg.books.adapters.open_library import (
    _OL_HEADERS,
    OpenLibraryClient,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    """Build a lightweight mock that mimics an httpx.Response."""
    response = MagicMock()
    response.status_code = status_code
    if json_data is not None:
        response.json = MagicMock(return_value=json_data)
    return response


def _trending_payload(works: list[dict]) -> dict:
    return {"works": works}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trending_books_sends_user_agent_header():
    """get_trending_books must include the User-Agent header in its HTTP request."""

    async def fake_get(url, params=None):  # noqa: ARG001
        return _mock_response(200, _trending_payload([]))

    mock_client = AsyncMock()
    mock_client.get = fake_get

    # Capture the headers passed to AsyncClient's constructor
    original_headers: dict = {}

    class CapturingClient:
        def __init__(self, headers=None, **kwargs):
            nonlocal original_headers
            original_headers = headers or {}

        async def __aenter__(self):
            return mock_client

        async def __aexit__(self, *args):
            pass

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", CapturingClient):
        client = OpenLibraryClient()
        await client.get_trending_books(limit=1)

    assert "User-Agent" in original_headers
    assert original_headers["User-Agent"] == _OL_HEADERS["User-Agent"]


@pytest.mark.asyncio
async def test_get_trending_books_returns_empty_list_on_403():
    """get_trending_books must return [] (and not raise) when the API returns 403."""

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            return _mock_response(403)

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        result = await client.get_trending_books(limit=10)

    assert result == []


@pytest.mark.asyncio
async def test_get_trending_books_parses_works_list():
    """get_trending_books must return the list of works from a successful response."""
    fake_works = [
        {"key": "/works/OL1W", "title": "Book One"},
        {"key": "/works/OL2W", "title": "Book Two"},
    ]

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            # Return fewer items than per_page so the loop terminates after one page
            return _mock_response(200, _trending_payload(fake_works))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        result = await client.get_trending_books(limit=10)

    assert len(result) == 2
    assert result[0]["key"] == "/works/OL1W"
    assert result[1]["title"] == "Book Two"


# ---------------------------------------------------------------------------
# get_author retry tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_author_returns_none_after_three_timeouts():
    """get_author must return None (not raise) after 3 consecutive TimeoutExceptions."""
    call_count = 0

    class TimeoutClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectTimeout("timed out")

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", TimeoutClient):
        with patch("backlogg.books.adapters.open_library.asyncio.sleep", AsyncMock()):
            ol = OpenLibraryClient()
            result = await ol.get_author("OL123A")

    assert result is None
    assert call_count == 3


@pytest.mark.asyncio
async def test_get_author_succeeds_on_retry_after_timeout():
    """get_author must return data when a retry succeeds after an initial timeout."""
    attempts = 0
    author_data = {"key": "/authors/OL123A", "name": "Test Author"}

    class FlakyClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectTimeout("first attempt fails")
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=author_data)
            resp.raise_for_status = MagicMock()
            return resp

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FlakyClient):
        with patch("backlogg.books.adapters.open_library.asyncio.sleep", AsyncMock()):
            ol = OpenLibraryClient()
            result = await ol.get_author("OL123A")

    assert result == author_data
    assert attempts == 2


@pytest.mark.asyncio
async def test_get_author_returns_none_on_404():
    """get_author must return None when the API returns 404."""

    class NotFoundClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            resp = MagicMock()
            resp.status_code = 404
            return resp

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", NotFoundClient):
        ol = OpenLibraryClient()
        result = await ol.get_author("OL999A")

    assert result is None
