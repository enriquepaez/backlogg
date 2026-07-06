"""Tests for the OpenLibraryClient adapter.

Covers:
- User-Agent header is sent in get_popular_books requests
- get_popular_books queries /search.json with q=*:*, sort=readinglog and
  native offset/limit, requesting the field set book_to_dict consumes
- get_popular_books raises immediately (no retry) when the API responds with 403
- get_popular_books retries transient 5xx responses and succeeds on a later attempt
- get_popular_books raises after exhausting the 5xx retries, including
  mid-pagination (accumulated pages are discarded, never returned as success)
- get_popular_books correctly parses a response containing a non-empty "docs" list
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
    _is_clean_genre,
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
    if status_code >= 400:
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"HTTP {status_code}", request=MagicMock(), response=response
            )
        )
    else:
        response.raise_for_status = MagicMock()
    return response


def _search_payload(docs: list[dict]) -> dict:
    return {"numFound": len(docs), "docs": docs}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_popular_books_sends_user_agent_header():
    """get_popular_books must include the User-Agent header in its HTTP request."""

    async def fake_get(url, params=None):  # noqa: ARG001
        return _mock_response(200, _search_payload([]))

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
        await client.get_popular_books(limit=1)

    assert "User-Agent" in original_headers
    assert original_headers["User-Agent"] == _OL_HEADERS["User-Agent"]


@pytest.mark.asyncio
async def test_get_popular_books_queries_search_json_with_readinglog_sort():
    """get_popular_books must hit /search.json with q=*:*, sort=readinglog,
    native offset/limit and the field set consumed by book_to_dict."""
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return _mock_response(200, _search_payload([]))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        await client.get_popular_books(limit=5, offset=120)

    assert captured["url"].endswith("/search.json")
    assert captured["params"]["q"] == "*:*"
    assert captured["params"]["sort"] == "readinglog"
    assert captured["params"]["offset"] == 120
    assert captured["params"]["limit"] == 5
    assert (
        captured["params"]["fields"]
        == "key,title,author_name,first_publish_year,cover_i,subject,isbn"
    )


@pytest.mark.asyncio
async def test_get_popular_books_raises_on_403_without_retry():
    """A 4xx (e.g. rate-limit 403) must raise immediately — no retry, no [] masking."""
    call_count = 0

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            return _mock_response(403)

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_popular_books(limit=10)

    assert call_count == 1  # 4xx is not retried


@pytest.mark.asyncio
async def test_get_popular_books_retries_5xx_and_succeeds_on_second_attempt():
    """A transient 5xx must be retried; the second attempt's 200 is returned."""
    fake_docs = [{"key": "/works/OL1W", "title": "Book One"}]
    call_count = 0

    class FlakyClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_response(500)
            return _mock_response(200, _search_payload(fake_docs))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FlakyClient):
        with patch("backlogg.books.adapters.open_library.asyncio.sleep", AsyncMock()) as mock_sleep:
            client = OpenLibraryClient()
            result = await client.get_popular_books(limit=10)

    assert result == fake_docs
    assert call_count == 2
    mock_sleep.assert_awaited_once()  # one backoff between the two attempts


@pytest.mark.asyncio
async def test_get_popular_books_raises_after_persistent_5xx():
    """A 5xx that survives all retry attempts must raise, never return []."""
    call_count = 0

    class BrokenClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            return _mock_response(500)

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", BrokenClient):
        with patch("backlogg.books.adapters.open_library.asyncio.sleep", AsyncMock()):
            client = OpenLibraryClient()
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_popular_books(limit=10)

    assert call_count == 3  # initial attempt + 2 retries


@pytest.mark.asyncio
async def test_get_popular_books_mid_pagination_error_discards_and_raises():
    """A persistent 5xx on a later page raises and discards earlier pages.

    A returned list must always mean a fully successful fetch: returning the
    accumulated pages would look like a legitimate short (end-of-results)
    response upstream and wrap the sync cursor to 0.
    """
    page_one = [{"key": f"/works/OL{i}W", "title": f"Book {i}"} for i in range(100)]
    call_count = 0

    class FlakySecondPageClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            if params["offset"] == 0:
                return _mock_response(200, _search_payload(page_one))
            return _mock_response(500)

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FlakySecondPageClient):
        with patch("backlogg.books.adapters.open_library.asyncio.sleep", AsyncMock()):
            client = OpenLibraryClient()
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_popular_books(limit=200, offset=0)

    assert call_count == 4  # page 1 OK + 3 failed attempts on page 2


@pytest.mark.asyncio
async def test_get_popular_books_parses_docs_list():
    """get_popular_books must return the list of search docs from a successful response."""
    fake_docs = [
        {
            "key": "/works/OL1W",
            "title": "Book One",
            "author_name": ["Author One"],
            "first_publish_year": 1999,
            "cover_i": 111,
            "subject": ["Fiction"],
        },
        {
            "key": "/works/OL2W",
            "title": "Book Two",
            "author_name": ["Author Two"],
            "first_publish_year": 2005,
            "cover_i": 222,
            "subject": ["Fantasy"],
        },
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
            return _mock_response(200, _search_payload(fake_docs))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        result = await client.get_popular_books(limit=10)

    assert len(result) == 2
    assert result[0]["key"] == "/works/OL1W"
    assert result[1]["title"] == "Book Two"
    # Each doc carries the fields book_to_dict consumes
    for doc in result:
        assert {"key", "title", "author_name", "first_publish_year", "cover_i", "subject"} <= set(
            doc
        )


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


# ---------------------------------------------------------------------------
# Genre filtering tests (_is_clean_genre + book_to_dict)
# ---------------------------------------------------------------------------


def test_is_clean_genre_rejects_parenthesised_subject():
    """Subjects containing parentheses must be filtered out."""
    assert _is_clean_genre("American fiction (fictional works by one author)") is False


def test_is_clean_genre_rejects_subject_with_comma():
    """Subjects containing commas must be filtered out."""
    assert _is_clean_genre("Long island (n.y.), fiction") is False


def test_is_clean_genre_rejects_long_subject():
    """Subjects longer than 30 characters with no punctuation still fail if > 30 chars."""
    long_subject = "A" * 31  # 31 chars, no parens/comma
    assert _is_clean_genre(long_subject) is False


def test_is_clean_genre_accepts_allowlist_entry():
    """A subject that matches the allowlist (case-insensitive) must pass."""
    assert _is_clean_genre("Fiction") is True
    assert _is_clean_genre("FANTASY") is True
    assert _is_clean_genre("science fiction") is True


def test_is_clean_genre_accepts_short_clean_subject():
    """A short subject with no parentheses or commas must pass."""
    assert _is_clean_genre("Magic") is True
    assert _is_clean_genre("War") is True


def test_book_to_dict_filters_raw_subjects():
    """book_to_dict must exclude cataloguing subjects and keep only clean genres."""
    ol = OpenLibraryClient()
    search_doc = {
        "title": "Test Book",
        "first_publish_year": 2000,
        "subject": [
            "American fiction (fictional works by one author)",  # has parens -> out
            "Lectures et morceaux choisis",  # >30 chars -> out
            "Fiction",  # allowlist -> in
            "Fantasy",  # allowlist -> in
            "Long island (n.y.), fiction",  # parens + comma -> out
        ],
    }
    result = ol.book_to_dict(search_doc)
    genre_names = [g["name"] for g in result["genres"]]

    assert "American fiction (fictional works by one author)" not in genre_names
    assert "Lectures et morceaux choisis" not in genre_names
    assert "Long island (n.y.), fiction" not in genre_names
    assert "Fiction" in genre_names
    assert "Fantasy" in genre_names


def test_book_to_dict_caps_genres_at_five():
    """book_to_dict must return at most 5 genres even when more clean subjects exist."""
    ol = OpenLibraryClient()
    # Provide 8 subjects that all pass the filter (all in allowlist or short+clean)
    search_doc = {
        "title": "Genre Rich Book",
        "first_publish_year": 2010,
        "subject": [
            "Fiction",
            "Fantasy",
            "Mystery",
            "Thriller",
            "Horror",
            "Romance",
            "Science",
            "History",
        ],
    }
    result = ol.book_to_dict(search_doc)
    assert len(result["genres"]) == 5
