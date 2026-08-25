"""Tests for the catalog search endpoint (GET /search)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo


def _movie_dict(slug: str = "inception-2010") -> dict:
    return {
        "title": "Inception",
        "original_title": "Inception",
        "slug": slug,
        "overview": "A thief who steals corporate secrets.",
        "release_date": date(2010, 7, 16),
        "runtime": 148,
        "original_language": "en",
        "poster_url": "https://example.com/inception.jpg",
        "backdrop_url": None,
        "budget": 160000000,
        "revenue": 836836967,
        "status": "Released",
        "rating_external": 8.4,
        "rating_count_external": 30000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _series_dict(slug: str = "breaking-bad-2008") -> dict:
    return {
        "title": "Breaking Bad",
        "original_title": "Breaking Bad",
        "slug": slug,
        "overview": "A high school chemistry teacher turned drug lord.",
        "first_air_date": date(2008, 1, 20),
        "last_air_date": date(2013, 9, 29),
        "number_of_seasons": 5,
        "number_of_episodes": 62,
        "status": "Ended",
        "original_language": "en",
        "poster_url": "https://example.com/bb.jpg",
        "backdrop_url": None,
        "rating_external": 9.5,
        "rating_count_external": 25000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _book_dict(slug: str = "dune-1965") -> dict:
    return {
        "title": "Dune",
        "original_title": "Dune",
        "slug": slug,
        "overview": "An epic tale of politics on a desert planet.",
        "first_publish_date": date(1965, 8, 1),
        "original_language": "en",
        "poster_url": "https://example.com/dune.jpg",
        "rating_external": 8.7,
        "rating_count_external": 15000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _game_dict(slug: str = "witcher-3-2015") -> dict:
    return {
        "title": "The Witcher 3",
        "original_title": "The Witcher 3: Wild Hunt",
        "slug": slug,
        "overview": "An open-world RPG set in a fantasy universe.",
        "release_date": date(2015, 5, 19),
        "game_type": "MAIN_GAME",
        "original_language": "en",
        "poster_url": "https://example.com/witcher3.jpg",
        "backdrop_url": None,
        "rating_external": 9.3,
        "rating_count_external": 20000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }


_REFRESH_PATCH = "backlogg.search.repository.SearchRepository.refresh_catalog_search"


@pytest_asyncio.fixture(autouse=True)
async def _no_real_fanout_by_default():
    """Prevent accidental real external-API calls for tests that don't opt in.

    Issue #14 widened the fallback trigger from "0 local results" to "local
    page shorter than limit", so most fixtures in this module (which seed far
    fewer than the default limit=20) would otherwise silently fan out to the
    real TMDB/Open Library/IGDB APIs and commit real rows through the
    production ``async_session_factory`` (which bypasses this file's
    per-test rollback, polluting later tests in the same session). Tests
    that specifically exercise the fallback patch these same targets
    themselves inside a nested ``with``, which takes precedence for the
    duration of that block.
    """
    with (
        patch("backlogg.search.service._ingest_movies", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_series", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_books", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_games", new=AsyncMock(return_value=None)),
        patch(_REFRESH_PATCH, new=AsyncMock(return_value=None)),
    ):
        yield


@pytest_asyncio.fixture
async def client(db):
    """AsyncClient wired to the FastAPI app, using the test DB session."""
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_db(db):
    """Seed one item of each type, then refresh the materialized view."""
    await movies_repo.upsert_movie(db, _movie_dict("inception-2010-search-test"))
    await series_repo.upsert_series(db, _series_dict("breaking-bad-2008-search-test"))
    await books_repo.upsert_book(db, _book_dict("dune-1965-search-test"))
    await games_repo.upsert_game(db, _game_dict("witcher-3-2015-search-test"))
    await db.flush()
    # Refresh the materialized view so the inserted rows are visible to search
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))
    return db


async def test_search_returns_results(client, seeded_db):
    """GET /search?q=inception returns 200 with matching movie."""
    response = await client.get("/v1/search?q=inception")
    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    assert "total" in body
    slugs = [r["slug"] for r in body["results"]]
    assert "inception-2010-search-test" in slugs


async def test_search_filter_by_type(client, seeded_db):
    """GET /search?q=inception&type=movie returns only movie results."""
    response = await client.get("/v1/search?q=inception&type=movie")
    assert response.status_code == 200
    body = response.json()
    for result in body["results"]:
        assert result["item_type"] == "MOVIE"
    slugs = [r["slug"] for r in body["results"]]
    assert "inception-2010-search-test" in slugs


async def test_search_filter_by_type_excludes_others(client, seeded_db):
    """GET /search?q=inception&type=series returns no movie results."""
    response = await client.get("/v1/search?q=inception&type=series")
    assert response.status_code == 200
    body = response.json()
    for result in body["results"]:
        assert result["item_type"] == "SERIES"
    # inception-2010-search-test is a movie, so it must not appear in series results
    slugs = [r["slug"] for r in body["results"]]
    assert "inception-2010-search-test" not in slugs


async def test_search_pagination(client, seeded_db):
    """GET /search?q=inception&page=1&limit=5 returns correct pagination fields.

    Only 1 local movie matches "inception" (seeded_db), so limit=5 makes this
    page incomplete and the fan-out would fire — mocked here since this test
    only cares about the pagination response fields, not the fallback.
    """
    with (
        patch("backlogg.search.service._ingest_movies", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_series", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_books", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_games", new=AsyncMock(return_value=None)),
        patch(_REFRESH_PATCH, new=AsyncMock(return_value=None)),
    ):
        response = await client.get("/v1/search?q=inception&page=1&limit=5")
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["limit"] == 5
    assert "total" in body
    assert isinstance(body["results"], list)


async def test_search_missing_q_returns_200(client, seeded_db):
    """GET /search without q parameter is now a valid pure-filter query (200)."""
    response = await client.get("/v1/search")
    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    assert "total" in body


async def test_search_empty_q_returns_422(client, seeded_db):
    """GET /search?q= (empty string) returns 422."""
    response = await client.get("/v1/search?q=")
    assert response.status_code == 422


async def test_search_no_results(client, seeded_db):
    """GET /search?q=<nonexistent> returns 200 with empty results when APIs find nothing."""
    with (
        patch(
            "backlogg.search.service._ingest_movies",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.search.service._ingest_series",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.search.service._ingest_books",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.search.service._ingest_games",
            new=AsyncMock(return_value=None),
        ),
        patch(_REFRESH_PATCH, new=AsyncMock(return_value=None)),
    ):
        response = await client.get("/v1/search?q=xxxxxxxxxxxxxxxxxxxxxxxx_inexistente")
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["total"] == 0


async def test_search_result_fields(client, seeded_db):
    """Each result item includes the expected fields."""
    response = await client.get("/v1/search?q=inception")
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) > 0
    item = body["results"][0]
    expected_fields = (
        "id",
        "item_type",
        "slug",
        "title",
        "poster_url",
        "release_date",
        "rating_external",
    )
    for field in expected_fields:
        assert field in item


# ---------------------------------------------------------------------------
# External fallback tests
# ---------------------------------------------------------------------------


async def test_search_fallback_fires_when_no_local_results(client, seeded_db):
    """When local search returns 0 results, all 4 ingest functions are called."""
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=xxxxxxxxxxxxxxxxxxxxxxxx_inexistente")

    assert response.status_code == 200
    # All four ingest helpers must have been called exactly once
    ingest_movie_mock.assert_called_once()
    ingest_series_mock.assert_called_once()
    ingest_books_mock.assert_called_once()
    ingest_games_mock.assert_called_once()
    # Materialized view refresh must have been called
    refresh_mock.assert_called_once()


async def test_search_fallback_page1_fires_first_time_even_when_local_page_full(client, seeded_db):
    """Page 1 fires the fan-out at least once even when already full (issue #14 follow-up).

    seeded_db seeds exactly 1 movie matching "inception" — limit=1 makes the
    page complete. Before this fix a fully-populated page 1 never fanned out
    at all, so a broad/popular query with plenty of local rows (e.g. "final
    fantasy") could never surface an item missing from the local catalog.
    The first request for a given q/item_type must still check externally.
    """
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=inception&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    ingest_movie_mock.assert_called_once()
    ingest_series_mock.assert_called_once()
    ingest_books_mock.assert_called_once()
    ingest_games_mock.assert_called_once()
    refresh_mock.assert_called_once()


async def test_search_fallback_page1_not_refired_within_ttl_for_same_query(client, seeded_db):
    """A second identical page-1 request within the cache TTL must NOT fan out again."""
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        first = await client.get("/v1/search?q=inception&limit=1")
        second = await client.get("/v1/search?q=inception&limit=1")

    assert first.status_code == 200
    assert second.status_code == 200
    # Only the first request fanned out — the second hit the TTL cache.
    ingest_movie_mock.assert_called_once()
    ingest_series_mock.assert_called_once()
    ingest_books_mock.assert_called_once()
    ingest_games_mock.assert_called_once()
    refresh_mock.assert_called_once()


async def test_search_fallback_page1_different_item_type_fires_separately(client, seeded_db, db):
    """The page-1 dedup cache is scoped per item_type, not just per query text.

    Both `type=movie` and `type=series` are seeded with a full page (1 local
    result each, limit=1), so neither would fire due to an incomplete page —
    the only reason a second, different-type request still fans out is that
    the page-1 dedup cache is keyed per item_type, not just per query text.
    """
    await series_repo.upsert_series(
        db,
        _series_dict("inception-series-2010-search-test")
        | {"title": "Inception Chronicles", "original_title": "Inception Chronicles"},
    )
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_games", new=AsyncMock(return_value=None)),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        movie_response = await client.get("/v1/search?q=inception&limit=1&type=movie")
        series_response = await client.get("/v1/search?q=inception&limit=1&type=series")

    assert movie_response.status_code == 200
    assert series_response.status_code == 200
    assert len(movie_response.json()["results"]) == 1
    assert len(series_response.json()["results"]) == 1
    ingest_movie_mock.assert_called_once()
    ingest_series_mock.assert_called_once()
    assert refresh_mock.call_count == 2


async def test_search_fallback_page_gt1_still_fires_when_incomplete_after_page1_cached(
    client, seeded_db
):
    """Pages beyond 1 keep firing on an incomplete page regardless of the page-1 cache.

    First, a page-1 request marks the q/item_type pair as "checked" in the
    dedup cache. A subsequent page=2 request for the same query, whose local
    page comes back incomplete, must still fan out — the page-1 dedup cache
    must never be read/consulted to suppress an incomplete-page fan-out, only
    to skip a redundant already-full page-1 fan-out (regression guard for
    the "load more" pagination flow approved in earlier issue #14 rounds).
    """
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        page1 = await client.get("/v1/search?q=inception&limit=1")
        page2 = await client.get("/v1/search?q=inception&limit=1&page=2")

    assert page1.status_code == 200
    assert page2.status_code == 200
    # Both requests fanned out — page 1 because it was never checked before,
    # page 2 because its local page came back incomplete (0 rows, limit=1).
    assert ingest_movie_mock.call_count == 2
    assert ingest_series_mock.call_count == 2
    assert ingest_books_mock.call_count == 2
    assert ingest_games_mock.call_count == 2
    assert refresh_mock.call_count == 2


async def test_search_fallback_fires_when_local_page_incomplete(client, seeded_db):
    """Even with non-zero local results, a page shorter than `limit` must fan out.

    Only 1 local movie matches "inception" — the default limit (20) makes
    this page incomplete, so the fallback must fire despite total > 0. This
    is the Issue #14 regression: the old trigger was `total == 0` only.
    """
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=inception")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    ingest_movie_mock.assert_called_once()
    ingest_series_mock.assert_called_once()
    ingest_books_mock.assert_called_once()
    ingest_games_mock.assert_called_once()
    refresh_mock.assert_called_once()


async def test_search_fallback_type_movie_only_calls_tmdb_movies(client, seeded_db):
    """?type=movie fan-out must only call the movie ingest, not others."""
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=xxxxxxxxxxxxxxxxxxxxxxxx_inexistente&type=movie")

    assert response.status_code == 200
    ingest_movie_mock.assert_called_once()
    ingest_series_mock.assert_not_called()
    ingest_books_mock.assert_not_called()
    ingest_games_mock.assert_not_called()


async def test_search_fallback_type_series_only_calls_tmdb_series(client, seeded_db):
    """?type=series fan-out must only call the series ingest."""
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=xxxxxxxxxxxxxxxxxxxxxxxx_inexistente&type=series")

    assert response.status_code == 200
    ingest_movie_mock.assert_not_called()
    ingest_series_mock.assert_called_once()
    ingest_books_mock.assert_not_called()
    ingest_games_mock.assert_not_called()


async def test_search_fallback_type_book_only_calls_open_library(client, seeded_db):
    """?type=book fan-out must only call the book ingest."""
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=xxxxxxxxxxxxxxxxxxxxxxxx_inexistente&type=book")

    assert response.status_code == 200
    ingest_movie_mock.assert_not_called()
    ingest_series_mock.assert_not_called()
    ingest_books_mock.assert_called_once()
    ingest_games_mock.assert_not_called()


async def test_search_fallback_type_game_only_calls_igdb(client, seeded_db):
    """?type=game fan-out must only call the game ingest."""
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=xxxxxxxxxxxxxxxxxxxxxxxx_inexistente&type=game")

    assert response.status_code == 200
    ingest_movie_mock.assert_not_called()
    ingest_series_mock.assert_not_called()
    ingest_books_mock.assert_not_called()
    ingest_games_mock.assert_called_once()


async def test_search_fallback_api_failure_does_not_abort_others(client, seeded_db):
    """A failure in one external API must not abort the others or return 500."""

    async def failing_ingest(*args, **kwargs):
        raise RuntimeError("simulated API failure")

    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=failing_ingest),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=xxxxxxxxxxxxxxxxxxxxxxxx_inexistente")

    # Must still return 200 even though the movies ingest failed
    assert response.status_code == 200
    # The other ingests must have been called despite the movies failure
    ingest_series_mock.assert_called_once()
    ingest_books_mock.assert_called_once()
    ingest_games_mock.assert_called_once()


async def test_search_fallback_one_ingest_failure_does_not_abort_others(client, seeded_db):
    """If one _ingest_* raises an unhandled exception, the remaining ingests and
    refresh_catalog_search must still execute (each ingest owns its own session).
    """
    call_log: list[str] = []

    async def failing_movies_ingest(q, page, limit):
        raise RuntimeError("simulated movies session error")

    async def ok_series_ingest(q, page, limit):
        call_log.append("series")

    async def ok_books_ingest(q, page, limit):
        call_log.append("books")

    async def ok_games_ingest(q, page, limit):
        call_log.append("games")

    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=failing_movies_ingest),
        patch("backlogg.search.service._ingest_series", new=ok_series_ingest),
        patch("backlogg.search.service._ingest_books", new=ok_books_ingest),
        patch("backlogg.search.service._ingest_games", new=ok_games_ingest),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=xxxxxxxxxxxxxxxxxxxxxxxx_inexistente")

    # Must not 500 — each ingest has its own isolated session
    assert response.status_code == 200
    # The other ingests and refresh must have executed despite the movies failure
    assert "series" in call_log
    assert "books" in call_log
    assert "games" in call_log
    refresh_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Fan-out page mapping and multi-hit ingestion (issue #14)
# ---------------------------------------------------------------------------


async def test_search_fallback_page_2_maps_to_external_page(client, seeded_db):
    """page=2 with limit=10 must map to external page 1 (offset 10 // 20 + 1).

    _external_page((page-1)*limit=10, // _FANOUT_PAGE_SIZE=20) + 1 == 1.
    """
    ingest_movie_mock = AsyncMock(return_value=None)
    ingest_series_mock = AsyncMock(return_value=None)
    ingest_books_mock = AsyncMock(return_value=None)
    ingest_games_mock = AsyncMock(return_value=None)
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=ingest_series_mock),
        patch("backlogg.search.service._ingest_books", new=ingest_books_mock),
        patch("backlogg.search.service._ingest_games", new=ingest_games_mock),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?q=inception&page=2&limit=10")

    assert response.status_code == 200
    ingest_movie_mock.assert_called_once_with("inception", 2, 10)
    ingest_series_mock.assert_called_once_with("inception", 2, 10)
    ingest_books_mock.assert_called_once_with("inception", 2, 10)
    ingest_games_mock.assert_called_once_with("inception", 2, 10)


async def test_search_fallback_page_3_maps_to_external_page_2(client, seeded_db):
    """page=3 with limit=10 (offset=20) must map to external page 2."""
    from backlogg.search.service import _external_page

    assert _external_page(page=3, limit=10) == 2

    ingest_movie_mock = AsyncMock(return_value=None)

    with (
        patch("backlogg.search.service._ingest_movies", new=ingest_movie_mock),
        patch("backlogg.search.service._ingest_series", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_books", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_games", new=AsyncMock(return_value=None)),
        patch(_REFRESH_PATCH, new=AsyncMock(return_value=None)),
    ):
        response = await client.get("/v1/search?q=inception&page=3&limit=10")

    assert response.status_code == 200
    ingest_movie_mock.assert_called_once_with("inception", 3, 10)


# ---------------------------------------------------------------------------
# Punctuation normalization (issue #13) — searching without punctuation
# still finds titles that contain it, and vice versa, without duplicates.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def punctuation_seeded_db(db):
    """Seed movies with punctuated titles, then refresh the materialized view."""
    await movies_repo.upsert_movie(
        db,
        _movie_dict("spider-man-homecoming-2017-search-test")
        | {"title": "Spider-Man: Homecoming", "original_title": "Spider-Man: Homecoming"},
    )
    await movies_repo.upsert_movie(
        db,
        _movie_dict("marvels-spider-man-2018-search-test")
        | {"title": "Marvel's Spider-Man", "original_title": "Marvel's Spider-Man"},
    )
    await movies_repo.upsert_movie(
        db,
        _movie_dict("swat-2003-search-test") | {"title": "S.W.A.T.", "original_title": "S.W.A.T."},
    )
    await series_repo.upsert_series(
        db,
        _series_dict("x-men-97-2024-search-test")
        | {"title": "X-Men '97", "original_title": "X-Men '97"},
    )
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))
    return db


async def test_search_no_punctuation_finds_hyphenated_title(client, punctuation_seeded_db):
    """GET /search?q=Spiderman finds 'Spider-Man: Homecoming' (hyphenated title)."""
    response = await client.get("/v1/search?q=Spiderman")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "spider-man-homecoming-2017-search-test" in slugs


async def test_search_no_punctuation_finds_apostrophe_title(client, punctuation_seeded_db):
    """GET /search?q=xmen finds \"X-Men '97\" (apostrophe + hyphen in title)."""
    response = await client.get("/v1/search?q=xmen")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "x-men-97-2024-search-test" in slugs


async def test_search_no_punctuation_finds_possessive_title(client, punctuation_seeded_db):
    """GET /search?q=marvels finds \"Marvel's Spider-Man\" (possessive apostrophe)."""
    response = await client.get("/v1/search?q=marvels")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "marvels-spider-man-2018-search-test" in slugs


async def test_search_no_punctuation_finds_abbreviation_title(client, punctuation_seeded_db):
    """GET /search?q=swat finds \"S.W.A.T.\" (dotted abbreviation)."""
    response = await client.get("/v1/search?q=swat")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "swat-2003-search-test" in slugs


async def test_search_punctuated_query_still_finds_punctuated_title(client, punctuation_seeded_db):
    """No regression — querying WITH the original punctuation still matches."""
    response = await client.get("/v1/search?q=Spider-Man")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "spider-man-homecoming-2017-search-test" in slugs
    assert "marvels-spider-man-2018-search-test" in slugs


async def test_search_no_duplicate_results_for_punctuated_title(client, punctuation_seeded_db):
    """Each matching row appears exactly once — the extra normalized lexemes
    live in the same search_vector, not a duplicated row."""
    response = await client.get("/v1/search?q=Spiderman")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert slugs.count("spider-man-homecoming-2017-search-test") == 1


async def test_search_existing_plain_title_still_works(client, punctuation_seeded_db, seeded_db):
    """No regression — a plain (punctuation-free) title still matches as before."""
    response = await client.get("/v1/search?q=inception")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "inception-2010-search-test" in slugs
    assert slugs.count("inception-2010-search-test") == 1


# ---------------------------------------------------------------------------
# Relevance tie-break by rating_external (QA follow-up on issue #14) — when
# two items tie on ts_rank (e.g. identical title), the one with the higher
# rating_external must sort first, so obscure items don't outrank well-known
# ones purely by insertion order.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tied_rank_seeded_db(db):
    """Seed two movies with the identical title (same ts_rank for a query
    matching that title) but different rating_external, insertion order
    reversed relative to rating so a naive `id` tie-break would misorder
    them."""
    await movies_repo.upsert_movie(
        db,
        _movie_dict("obscure-remake-1999-search-test")
        | {
            "title": "The Great Adventure",
            "original_title": "The Great Adventure",
            "rating_external": 2.1,
        },
    )
    await movies_repo.upsert_movie(
        db,
        _movie_dict("famous-original-2010-search-test")
        | {
            "title": "The Great Adventure",
            "original_title": "The Great Adventure",
            "rating_external": 9.1,
        },
    )
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))
    return db


async def test_search_tied_rank_orders_by_rating_external_desc(client, tied_rank_seeded_db):
    """Two items tied on ts_rank (identical title) must be ordered with the
    higher rating_external first, not by insertion/id order."""
    response = await client.get("/v1/search?q=The Great Adventure")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "famous-original-2010-search-test" in slugs
    assert "obscure-remake-1999-search-test" in slugs
    famous_idx = slugs.index("famous-original-2010-search-test")
    obscure_idx = slugs.index("obscure-remake-1999-search-test")
    assert famous_idx < obscure_idx


@pytest_asyncio.fixture
async def distinct_rank_seeded_db(db):
    """Seed two movies that match the same query with genuinely DIFFERENT
    ts_rank (unlike ``tied_rank_seeded_db``), but with rating_external
    opposite to what ts_rank alone would suggest — mirrors the real "batman"
    search reported in issue #14 follow-up QA, where an unrated DLC-style
    item ("Batman: Arkham City - ... Skins Pack") outranked a well-rated,
    well-known title purely because repeated occurrences of the query word
    in its title inflated ts_rank. Verified against the real search_vector
    expression (0028 migration) that the repeated-word title's ts_rank is
    strictly higher than the single-occurrence title's."""
    await movies_repo.upsert_movie(
        db,
        _movie_dict("batman-1989-search-test")
        | {
            "title": "Batman",
            "original_title": "Batman",
            "overview": "The caped crusader.",
            "rating_external": 9.0,
        },
    )
    await movies_repo.upsert_movie(
        db,
        _movie_dict("batman-arkham-city-skins-pack-2012-search-test")
        | {
            "title": "Batman Batman Batman Arkham City Skins Pack",
            "original_title": "Batman Batman Batman Arkham City Skins Pack",
            "overview": "Cosmetic DLC skin pack.",
            "rating_external": None,
        },
    )
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))
    return db


async def test_search_distinct_rank_orders_by_rating_external_over_ts_rank(
    client, distinct_rank_seeded_db
):
    """When ts_rank genuinely differs between two matches, rating_external
    still wins: the higher-rated, lower-rank item must come before the
    unrated, higher-rank item. ts_rank only breaks ties within the same
    rating (issue #14 follow-up)."""
    response = await client.get("/v1/search?q=batman")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "batman-1989-search-test" in slugs
    assert "batman-arkham-city-skins-pack-2012-search-test" in slugs
    rated_idx = slugs.index("batman-1989-search-test")
    unrated_idx = slugs.index("batman-arkham-city-skins-pack-2012-search-test")
    assert rated_idx < unrated_idx


# ---------------------------------------------------------------------------
# Regression (feature 66 — rating_display_internal_only): SearchRepository
# .search() is the explicit exception that keeps ordering by rating_external
# DESC NULLS LAST — catalog_search has no rating_internal column, and even
# where the underlying row *does* have one, /search must never consult it.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def rating_internal_present_seeded_db(db):
    """Two movies matching the same query: one has a rating_internal set, the
    other doesn't — /search must still rank purely by rating_external, since
    rating_internal never enters the SearchRepository.search() query at all
    (feature 66 explicitly leaves this repository untouched)."""
    await movies_repo.upsert_movie(
        db,
        _movie_dict("f66-low-external-high-internal-search-test")
        | {
            "title": "Feature Sixtysix Regression Movie",
            "original_title": "Feature Sixtysix Regression Movie",
            "rating_external": 1.0,
            "rating_internal": 4.9,
        },
    )
    await movies_repo.upsert_movie(
        db,
        _movie_dict("f66-high-external-no-internal-search-test")
        | {
            "title": "Feature Sixtysix Regression Movie",
            "original_title": "Feature Sixtysix Regression Movie",
            "rating_external": 9.0,
            "rating_internal": None,
        },
    )
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))
    return db


async def test_search_still_orders_by_rating_external_regardless_of_rating_internal(
    client, rating_internal_present_seeded_db
):
    """A high rating_internal never outranks a higher rating_external in /search."""
    response = await client.get("/v1/search?q=Feature Sixtysix Regression Movie")
    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "f66-high-external-no-internal-search-test" in slugs
    assert "f66-low-external-high-internal-search-test" in slugs
    high_ext_idx = slugs.index("f66-high-external-no-internal-search-test")
    low_ext_idx = slugs.index("f66-low-external-high-internal-search-test")
    assert high_ext_idx < low_ext_idx
    # rating_internal is not even part of the response contract for /search.
    assert "rating_internal" not in body["results"][0]


async def test_search_fallback_returns_ingested_items(client, db):
    """After ingestion, items appear in search results (end-to-end with real ingest)."""
    # Pre-seed a movie that will be "found" by the external fallback
    movie_data = {
        "title": "Galactic Traveler",
        "original_title": "Galactic Traveler",
        "slug": "galactic-traveler-2020",
        "overview": "A unique cosmic adventure.",
        "release_date": date(2020, 6, 15),
        "runtime": 120,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": 7.5,
        "rating_count_external": 1000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }

    async def fake_ingest_movies(q, page, limit):
        await movies_repo.upsert_movie(db, dict(movie_data))
        await db.flush()

    async def fake_refresh(self):
        await self._session.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with (
            patch("backlogg.search.service._ingest_movies", new=fake_ingest_movies),
            patch("backlogg.search.service._ingest_series", new=AsyncMock(return_value=None)),
            patch("backlogg.search.service._ingest_books", new=AsyncMock(return_value=None)),
            patch("backlogg.search.service._ingest_games", new=AsyncMock(return_value=None)),
            patch(_REFRESH_PATCH, new=fake_refresh),
        ):
            response = await ac.get("/v1/search?q=galactic+traveler")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    slugs = [r["slug"] for r in body["results"]]
    assert "galactic-traveler-2020" in slugs
