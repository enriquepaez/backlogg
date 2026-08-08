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
    """GET /search?q=inception&page=1&limit=5 returns correct pagination fields."""
    response = await client.get("/v1/search?q=inception&page=1&limit=5")
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["limit"] == 5
    assert "total" in body
    assert isinstance(body["results"], list)


async def test_search_missing_q_returns_422(client, seeded_db):
    """GET /search without q parameter returns 422."""
    response = await client.get("/v1/search")
    assert response.status_code == 422


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

_REFRESH_PATCH = "backlogg.search.repository.SearchRepository.refresh_catalog_search"


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


async def test_search_fallback_not_fired_when_local_results_exist(client, seeded_db):
    """When local results exist the fan-out must NOT be triggered."""
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
    # Fast path — no external calls
    ingest_movie_mock.assert_not_called()
    ingest_series_mock.assert_not_called()
    ingest_books_mock.assert_not_called()
    ingest_games_mock.assert_not_called()
    refresh_mock.assert_not_called()


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

    async def failing_movies_ingest(q):
        raise RuntimeError("simulated movies session error")

    async def ok_series_ingest(q):
        call_log.append("series")

    async def ok_books_ingest(q):
        call_log.append("books")

    async def ok_games_ingest(q):
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

    async def fake_ingest_movies(q):
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
