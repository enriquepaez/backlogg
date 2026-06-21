"""Tests for the GET /trending endpoint (feature #20)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.movies import repository as movies_repo

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _raw_movie(tmdb_id: int = 1001, slug_title: str = "trending-movie") -> dict:
    """Minimal TMDB trending list-format movie dict."""
    return {
        "id": tmdb_id,
        "title": slug_title.replace("-", " ").title(),
        "release_date": "2023-06-15",
        "poster_path": "/trending_movie.jpg",
        "vote_average": 7.8,
        "vote_count": 5000,
        "overview": "A trending film.",
        "original_title": slug_title.replace("-", " ").title(),
        "original_language": "en",
        "backdrop_path": None,
    }


def _raw_series(tmdb_id: int = 2001, slug_title: str = "trending-series") -> dict:
    """Minimal TMDB trending list-format series dict."""
    return {
        "id": tmdb_id,
        "name": slug_title.replace("-", " ").title(),
        "first_air_date": "2022-09-01",
        "poster_path": "/trending_series.jpg",
        "vote_average": 8.1,
        "vote_count": 4000,
        "overview": "A trending show.",
        "original_name": slug_title.replace("-", " ").title(),
        "original_language": "en",
        "backdrop_path": None,
    }


def _tmdb_movie_detail(tmdb_id: int = 1001, title: str = "Trending Movie") -> dict:
    return {
        "id": tmdb_id,
        "title": title,
        "original_title": title,
        "overview": "A trending film.",
        "release_date": "2023-06-15",
        "runtime": 120,
        "original_language": "en",
        "poster_path": "/trending_movie.jpg",
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 7.8,
        "vote_count": 5000,
        "genres": [{"id": 28, "name": "Action"}],
    }


def _tmdb_series_detail(tmdb_id: int = 2001, title: str = "Trending Series") -> dict:
    return {
        "id": tmdb_id,
        "name": title,
        "original_name": title,
        "overview": "A trending show.",
        "first_air_date": "2022-09-01",
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Returning Series",
        "original_language": "en",
        "poster_path": "/trending_series.jpg",
        "backdrop_path": None,
        "vote_average": 8.1,
        "vote_count": 4000,
        "genres": [{"id": 18, "name": "Drama"}],
        "created_by": [],
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


# ---------------------------------------------------------------------------
# Helper: pre-seed movies/series so the service finds them in local DB
# ---------------------------------------------------------------------------


def _movie_dict_for_db(slug: str, title: str = "Trending Movie") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A trending film.",
        "release_date": date(2023, 6, 15),
        "runtime": 120,
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/trending_movie.jpg",
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": 7.8,
        "rating_count_external": 5000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _series_dict_for_db(slug: str, title: str = "Trending Series") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A trending show.",
        "first_air_date": date(2022, 9, 1),
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Returning Series",
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/trending_series.jpg",
        "backdrop_url": None,
        "rating_external": 8.1,
        "rating_count_external": 4000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_trending_returns_200_with_mix(client, db):
    """GET /trending returns 200 with a mix of movies and series."""
    raw_movie = _raw_movie(tmdb_id=9001, slug_title="Test Trending Film")
    raw_series = _raw_series(tmdb_id=9002, slug_title="Test Trending Show")

    with (
        patch(
            "backlogg.trending.service._movies_tmdb.get_trending_movies",
            new=AsyncMock(return_value=[raw_movie]),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_trending_series",
            new=AsyncMock(return_value=[raw_series]),
        ),
        patch(
            "backlogg.trending.service._movies_tmdb.get_movie_detail",
            new=AsyncMock(return_value=_tmdb_movie_detail(9001, "Test Trending Film")),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_series_detail",
            new=AsyncMock(return_value=_tmdb_series_detail(9002, "Test Trending Show")),
        ),
    ):
        response = await client.get("/trending")

    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    assert len(body["results"]) > 0
    item_types = {r["item_type"] for r in body["results"]}
    assert "MOVIE" in item_types
    assert "SERIES" in item_types


async def test_trending_type_movie_only(client, db):
    """GET /trending?type=movie returns only movie results."""
    raw_movie = _raw_movie(tmdb_id=9003, slug_title="Only Movie Trending")

    with (
        patch(
            "backlogg.trending.service._movies_tmdb.get_trending_movies",
            new=AsyncMock(return_value=[raw_movie]),
        ),
        patch(
            "backlogg.trending.service._movies_tmdb.get_movie_detail",
            new=AsyncMock(return_value=_tmdb_movie_detail(9003, "Only Movie Trending")),
        ),
    ):
        response = await client.get("/trending?type=movie")

    assert response.status_code == 200
    body = response.json()
    assert all(r["item_type"] == "MOVIE" for r in body["results"])


async def test_trending_type_series_only(client, db):
    """GET /trending?type=series returns only series results."""
    raw_series = _raw_series(tmdb_id=9004, slug_title="Only Series Trending")

    with (
        patch(
            "backlogg.trending.service._series_tmdb.get_trending_series",
            new=AsyncMock(return_value=[raw_series]),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_series_detail",
            new=AsyncMock(return_value=_tmdb_series_detail(9004, "Only Series Trending")),
        ),
    ):
        response = await client.get("/trending?type=series")

    assert response.status_code == 200
    body = response.json()
    assert all(r["item_type"] == "SERIES" for r in body["results"])


async def test_trending_period_day(client, db):
    """GET /trending?period=day calls TMDB with period=day."""
    raw_movie = _raw_movie(tmdb_id=9005, slug_title="Day Trending Movie")
    raw_series = _raw_series(tmdb_id=9006, slug_title="Day Trending Show")

    movies_mock = AsyncMock(return_value=[raw_movie])
    series_mock = AsyncMock(return_value=[raw_series])

    with (
        patch("backlogg.trending.service._movies_tmdb.get_trending_movies", new=movies_mock),
        patch("backlogg.trending.service._series_tmdb.get_trending_series", new=series_mock),
        patch(
            "backlogg.trending.service._movies_tmdb.get_movie_detail",
            new=AsyncMock(return_value=_tmdb_movie_detail(9005, "Day Trending Movie")),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_series_detail",
            new=AsyncMock(return_value=_tmdb_series_detail(9006, "Day Trending Show")),
        ),
    ):
        response = await client.get("/trending?period=day")

    assert response.status_code == 200
    movies_mock.assert_called_once_with("day")
    series_mock.assert_called_once_with("day")


async def test_trending_period_week(client, db):
    """GET /trending?period=week calls TMDB with period=week (and is the default)."""
    raw_movie = _raw_movie(tmdb_id=9007, slug_title="Week Trending Movie")
    raw_series = _raw_series(tmdb_id=9008, slug_title="Week Trending Show")

    movies_mock = AsyncMock(return_value=[raw_movie])
    series_mock = AsyncMock(return_value=[raw_series])

    with (
        patch("backlogg.trending.service._movies_tmdb.get_trending_movies", new=movies_mock),
        patch("backlogg.trending.service._series_tmdb.get_trending_series", new=series_mock),
        patch(
            "backlogg.trending.service._movies_tmdb.get_movie_detail",
            new=AsyncMock(return_value=_tmdb_movie_detail(9007, "Week Trending Movie")),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_series_detail",
            new=AsyncMock(return_value=_tmdb_series_detail(9008, "Week Trending Show")),
        ),
    ):
        response = await client.get("/trending?period=week")

    assert response.status_code == 200
    movies_mock.assert_called_once_with("week")
    series_mock.assert_called_once_with("week")


async def test_trending_default_period_is_week(client, db):
    """GET /trending (no period param) defaults to week."""
    raw_movie = _raw_movie(tmdb_id=9009, slug_title="Default Period Movie")
    raw_series = _raw_series(tmdb_id=9010, slug_title="Default Period Show")

    movies_mock = AsyncMock(return_value=[raw_movie])
    series_mock = AsyncMock(return_value=[raw_series])

    with (
        patch("backlogg.trending.service._movies_tmdb.get_trending_movies", new=movies_mock),
        patch("backlogg.trending.service._series_tmdb.get_trending_series", new=series_mock),
        patch(
            "backlogg.trending.service._movies_tmdb.get_movie_detail",
            new=AsyncMock(return_value=_tmdb_movie_detail(9009, "Default Period Movie")),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_series_detail",
            new=AsyncMock(return_value=_tmdb_series_detail(9010, "Default Period Show")),
        ),
    ):
        response = await client.get("/trending")

    assert response.status_code == 200
    movies_mock.assert_called_once_with("week")
    series_mock.assert_called_once_with("week")


async def test_trending_invalid_type_returns_422(client, db):
    """GET /trending?type=invalid returns 422 (Pydantic validation error)."""
    response = await client.get("/trending?type=invalid")
    assert response.status_code == 422


async def test_trending_result_fields(client, db):
    """Each result includes item_type, title, slug, poster_url, release_date, rating_external."""
    raw_movie = _raw_movie(tmdb_id=9011, slug_title="Fields Check Movie")

    with (
        patch(
            "backlogg.trending.service._movies_tmdb.get_trending_movies",
            new=AsyncMock(return_value=[raw_movie]),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_trending_series",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "backlogg.trending.service._movies_tmdb.get_movie_detail",
            new=AsyncMock(return_value=_tmdb_movie_detail(9011, "Fields Check Movie")),
        ),
    ):
        response = await client.get("/trending?type=movie")

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) > 0
    item = body["results"][0]
    expected_fields = (
        "item_type",
        "title",
        "slug",
        "poster_url",
        "release_date",
        "rating_external",
    )
    for field in expected_fields:
        assert field in item, f"Missing field: {field}"


async def test_trending_items_persisted_in_db(client, db):
    """New trending items are persisted in the local DB."""
    raw_movie = _raw_movie(tmdb_id=9012, slug_title="Persist Test Movie")

    with (
        patch(
            "backlogg.trending.service._movies_tmdb.get_trending_movies",
            new=AsyncMock(return_value=[raw_movie]),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_trending_series",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "backlogg.trending.service._movies_tmdb.get_movie_detail",
            new=AsyncMock(return_value=_tmdb_movie_detail(9012, "Persist Test Movie")),
        ),
    ):
        response = await client.get("/trending?type=movie")

    assert response.status_code == 200
    # The movie must now exist in the local DB
    persisted = await movies_repo.get_movie_by_slug(db, "persist-test-movie-2023")
    assert persisted is not None
    assert persisted.title == "Persist Test Movie"


async def test_trending_up_to_20_items(client, db):
    """GET /trending returns at most 20 items."""
    # Create 15 movies + 15 series → after interleave and cap, must be ≤ 20
    raw_movies = [_raw_movie(tmdb_id=8000 + i, slug_title=f"Bulk Movie {i}") for i in range(15)]
    raw_series_list = [
        _raw_series(tmdb_id=8100 + i, slug_title=f"Bulk Series {i}") for i in range(15)
    ]

    def make_movie_detail(tmdb_id: int, i: int) -> dict:
        return _tmdb_movie_detail(tmdb_id, f"Bulk Movie {i}")

    def make_series_detail(tmdb_id: int, i: int) -> dict:
        return _tmdb_series_detail(tmdb_id, f"Bulk Series {i}")

    movie_detail_calls = [make_movie_detail(8000 + i, i) for i in range(15)]
    series_detail_calls = [make_series_detail(8100 + i, i) for i in range(15)]

    movie_detail_mock = AsyncMock(side_effect=movie_detail_calls)
    series_detail_mock = AsyncMock(side_effect=series_detail_calls)

    with (
        patch(
            "backlogg.trending.service._movies_tmdb.get_trending_movies",
            new=AsyncMock(return_value=raw_movies),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_trending_series",
            new=AsyncMock(return_value=raw_series_list),
        ),
        patch(
            "backlogg.trending.service._movies_tmdb.get_movie_detail",
            new=movie_detail_mock,
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_series_detail",
            new=series_detail_mock,
        ),
    ):
        response = await client.get("/trending")

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) <= 20


async def test_trending_items_found_in_db_skip_tmdb_detail(client, db):
    """Items already in local DB do not trigger a TMDB detail fetch."""
    # Pre-seed the movie so it's in DB
    slug = "pre-seeded-trending-movie-2023"
    await movies_repo.upsert_movie(db, _movie_dict_for_db(slug, "Pre Seeded Trending Movie"))
    await db.flush()

    raw_movie = {
        "id": 9099,
        "title": "Pre Seeded Trending Movie",
        "release_date": "2023-06-15",
        "poster_path": "/trending_movie.jpg",
        "vote_average": 7.8,
        "vote_count": 5000,
        "overview": "A trending film.",
        "original_title": "Pre Seeded Trending Movie",
        "original_language": "en",
        "backdrop_path": None,
    }

    detail_mock = AsyncMock(return_value=_tmdb_movie_detail(9099, "Pre Seeded Trending Movie"))

    with (
        patch(
            "backlogg.trending.service._movies_tmdb.get_trending_movies",
            new=AsyncMock(return_value=[raw_movie]),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_trending_series",
            new=AsyncMock(return_value=[]),
        ),
        patch("backlogg.trending.service._movies_tmdb.get_movie_detail", new=detail_mock),
    ):
        response = await client.get("/trending?type=movie")

    assert response.status_code == 200
    # Detail must NOT have been called since movie was already in DB
    detail_mock.assert_not_called()
