"""Tests for the GET /trending endpoint (feature #20)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo
from backlogg.shared.credits import get_credits_for_item

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


def _book_dict_for_db(
    slug: str,
    title: str = "Trending Book",
    rating_internal: float | None = None,
    rating_external: float | None = None,
) -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "A trending book.",
        "first_publish_date": date(1950, 1, 1),
        "original_language": "en",
        "poster_url": f"https://example.com/{slug}.jpg",
        "rating_external": rating_external,
        "rating_count_external": 200 if rating_external else None,
        "rating_internal": rating_internal,
        "rating_count_internal": 5 if rating_internal else 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _game_dict_for_db(
    slug: str,
    title: str = "Trending Game",
    rating_internal: float | None = None,
    rating_external: float | None = None,
) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A trending game.",
        "release_date": date(2020, 1, 1),
        "game_type": "main_game",
        "original_language": None,
        "poster_url": f"https://example.com/{slug}.jpg",
        "backdrop_url": None,
        "rating_external": rating_external,
        "rating_count_external": 1000 if rating_external else None,
        "rating_internal": rating_internal,
        "rating_count_internal": 5 if rating_internal else 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
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
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.series.service._tmdb.get_series_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending")

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
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending?type=movie")

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
        patch(
            "backlogg.series.service._tmdb.get_series_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending?type=series")

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
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.series.service._tmdb.get_series_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending?period=day")

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
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.series.service._tmdb.get_series_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending?period=week")

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
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.series.service._tmdb.get_series_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending")

    assert response.status_code == 200
    movies_mock.assert_called_once_with("week")
    series_mock.assert_called_once_with("week")


async def test_trending_invalid_type_returns_422(client, db):
    """GET /trending?type=invalid returns 422 (Pydantic validation error)."""
    response = await client.get("/v1/trending?type=invalid")
    assert response.status_code == 422


async def test_trending_result_fields(client, db):
    """Each result includes item_type, title, slug, poster_url, release_date,
    rating_external, rating_internal (feature 69)."""
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
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending?type=movie")

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
        "rating_internal",
    )
    for field in expected_fields:
        assert field in item, f"Missing field: {field}"


async def test_trending_result_includes_rating_internal_from_local_movie(client, db):
    """Feature 69: a pre-seeded local movie's rating_internal travels in the
    trending response (a fresh TMDB-only item has none, so seed one locally
    with a community rating already set)."""
    await movies_repo.upsert_movie(
        db,
        {
            "title": "Rating Internal Trending Movie",
            "original_title": "Rating Internal Trending Movie",
            "slug": "rating-internal-trending-movie-2023",
            "overview": "A trending film with a community rating.",
            "release_date": date(2023, 6, 15),
            "runtime": 120,
            "original_language": "en",
            "poster_url": "https://example.com/rating-internal-trending-movie.jpg",
            "backdrop_url": None,
            "budget": None,
            "revenue": None,
            "status": "Released",
            "rating_external": 7.8,
            "rating_count_external": 5000,
            "rating_internal": 4.1,
            "rating_count_internal": 9,
            "last_synced_at": datetime.now(UTC),
            "genres": [],
        },
    )
    raw_movie = _raw_movie(tmdb_id=9013, slug_title="Rating Internal Trending Movie")

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
            new=AsyncMock(),
        ) as mock_detail,
    ):
        response = await client.get("/v1/trending?type=movie")

    assert response.status_code == 200
    # Found locally — no detail fetch needed.
    mock_detail.assert_not_called()
    body = response.json()
    item = next(r for r in body["results"] if r["slug"] == "rating-internal-trending-movie-2023")
    assert item["rating_internal"] == 4.1


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
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending?type=movie")

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
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.series.service._tmdb.get_series_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending")

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
        response = await client.get("/v1/trending?type=movie")

    assert response.status_code == 200
    # Detail must NOT have been called since movie was already in DB
    detail_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Feature 68 — books/games via the local popularity heuristic
# ---------------------------------------------------------------------------


async def test_trending_type_book_returns_seeded_books_ranked_by_rating_internal(client, db):
    """GET /trending?type=book ranks by rating_internal DESC NULLS LAST,
    with rating_external DESC NULLS LAST as tie-break (feature 66 heuristic).
    No external API call is involved — books are already persisted."""
    await books_repo.upsert_book(
        db,
        _book_dict_for_db(
            "book-low-internal", "Book Low Internal", rating_internal=2.0, rating_external=9.0
        ),
    )
    await books_repo.upsert_book(
        db,
        _book_dict_for_db(
            "book-high-internal", "Book High Internal", rating_internal=4.5, rating_external=1.0
        ),
    )
    await books_repo.upsert_book(
        db,
        _book_dict_for_db(
            "book-no-rating", "Book No Rating", rating_internal=None, rating_external=None
        ),
    )

    response = await client.get("/v1/trending?type=book")

    assert response.status_code == 200
    body = response.json()
    assert all(r["item_type"] == "BOOK" for r in body["results"])
    slugs = [r["slug"] for r in body["results"]]
    # High rating_internal must rank before low rating_internal, which must
    # rank before the NULL-rating_internal book — regardless of rating_external.
    assert slugs.index("book-high-internal") < slugs.index("book-low-internal")
    assert slugs.index("book-low-internal") < slugs.index("book-no-rating")


async def test_trending_type_game_returns_seeded_games_ranked_by_rating_internal(client, db):
    """GET /trending?type=game uses the same heuristic as books (feature 68)."""
    await games_repo.upsert_game(
        db,
        _game_dict_for_db(
            "game-low-internal", "Game Low Internal", rating_internal=2.0, rating_external=9.5
        ),
    )
    await games_repo.upsert_game(
        db,
        _game_dict_for_db(
            "game-high-internal", "Game High Internal", rating_internal=4.8, rating_external=1.0
        ),
    )

    response = await client.get("/v1/trending?type=game")

    assert response.status_code == 200
    body = response.json()
    assert all(r["item_type"] == "GAME" for r in body["results"])
    slugs = [r["slug"] for r in body["results"]]
    assert slugs.index("game-high-internal") < slugs.index("game-low-internal")


async def test_trending_type_book_up_to_20_items(client, db):
    """GET /trending?type=book caps at 20 items even with more seeded books."""
    for i in range(25):
        await books_repo.upsert_book(db, _book_dict_for_db(f"book-cap-{i}", f"Book Cap {i}"))

    response = await client.get("/v1/trending?type=book")

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) <= 20


async def test_trending_type_book_period_has_no_effect(client, db):
    """period=day vs period=week return the same book results (documented
    limitation — the local heuristic has no time window)."""
    await books_repo.upsert_book(
        db, _book_dict_for_db("book-period-agnostic", "Book Period Agnostic", rating_internal=3.0)
    )

    day_response = await client.get("/v1/trending?type=book&period=day")
    week_response = await client.get("/v1/trending?type=book&period=week")

    assert day_response.status_code == 200
    assert week_response.status_code == 200
    day_slugs = {r["slug"] for r in day_response.json()["results"]}
    week_slugs = {r["slug"] for r in week_response.json()["results"]}
    assert day_slugs == week_slugs
    assert "book-period-agnostic" in day_slugs


async def test_trending_type_game_period_has_no_effect(client, db):
    """Same limitation as books applies to games (feature 68)."""
    await games_repo.upsert_game(
        db, _game_dict_for_db("game-period-agnostic", "Game Period Agnostic", rating_internal=3.0)
    )

    day_response = await client.get("/v1/trending?type=game&period=day")
    week_response = await client.get("/v1/trending?type=game&period=week")

    assert day_response.status_code == 200
    assert week_response.status_code == 200
    day_slugs = {r["slug"] for r in day_response.json()["results"]}
    week_slugs = {r["slug"] for r in week_response.json()["results"]}
    assert day_slugs == week_slugs
    assert "game-period-agnostic" in day_slugs


async def test_trending_type_book_result_fields(client, db):
    """Book trending items follow the same contract as movies/series."""
    await books_repo.upsert_book(
        db,
        _book_dict_for_db(
            "book-fields-check", "Book Fields Check", rating_internal=4.0, rating_external=4.4
        ),
    )

    response = await client.get("/v1/trending?type=book")

    assert response.status_code == 200
    body = response.json()
    item = next(r for r in body["results"] if r["slug"] == "book-fields-check")
    expected_fields = (
        "item_type",
        "title",
        "slug",
        "poster_url",
        "release_date",
        "rating_external",
        "rating_internal",
    )
    for field in expected_fields:
        assert field in item, f"Missing field: {field}"
    assert item["rating_internal"] == 4.0
    assert item["rating_external"] == 4.4


async def test_trending_type_game_result_fields(client, db):
    """Game trending items follow the same contract as movies/series."""
    await games_repo.upsert_game(
        db,
        _game_dict_for_db(
            "game-fields-check", "Game Fields Check", rating_internal=3.6, rating_external=8.2
        ),
    )

    response = await client.get("/v1/trending?type=game")

    assert response.status_code == 200
    body = response.json()
    item = next(r for r in body["results"] if r["slug"] == "game-fields-check")
    expected_fields = (
        "item_type",
        "title",
        "slug",
        "poster_url",
        "release_date",
        "rating_external",
        "rating_internal",
    )
    for field in expected_fields:
        assert field in item, f"Missing field: {field}"
    assert item["rating_internal"] == 3.6
    assert item["rating_external"] == 8.2


async def test_trending_no_type_mixes_four_types(client, db):
    """GET /trending without type mixes movies, series, books and games."""
    raw_movie = _raw_movie(tmdb_id=9101, slug_title="Mix Four Movie")
    raw_series = _raw_series(tmdb_id=9102, slug_title="Mix Four Series")
    await books_repo.upsert_book(
        db, _book_dict_for_db("mix-four-book", "Mix Four Book", rating_internal=4.0)
    )
    await games_repo.upsert_game(
        db, _game_dict_for_db("mix-four-game", "Mix Four Game", rating_internal=4.0)
    )

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
            new=AsyncMock(return_value=_tmdb_movie_detail(9101, "Mix Four Movie")),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_series_detail",
            new=AsyncMock(return_value=_tmdb_series_detail(9102, "Mix Four Series")),
        ),
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.series.service._tmdb.get_series_credits",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client.get("/v1/trending")

    assert response.status_code == 200
    body = response.json()
    item_types = {r["item_type"] for r in body["results"]}
    assert item_types == {"MOVIE", "SERIES", "BOOK", "GAME"}
    assert len(body["results"]) <= 20


async def test_trending_invalid_type_book_game_accepted(client, db):
    """type=book and type=game are valid enum values (no 422)."""
    book_response = await client.get("/v1/trending?type=book")
    game_response = await client.get("/v1/trending?type=game")
    assert book_response.status_code == 200
    assert game_response.status_code == 200


# ---------------------------------------------------------------------------
# Feature 70: catalog_credits_ingestion_parity
# ---------------------------------------------------------------------------
#
# Trending ingestion previously left movies/series without credits forever,
# because it upserted the row directly without ever calling
# _persist_movie_people/_persist_series_people — only the on-demand GET and
# the nightly job did.


async def test_trending_persists_movie_credits_for_new_movie(client, db):
    """A movie ingested via trending gets its cast+crew persisted too, not just the item row."""
    raw_movie = _raw_movie(tmdb_id=9201, slug_title="Trending Credits Movie")
    credits_data = {
        "cast": [
            {
                "id": 557001,
                "name": "Trending Credits Actor",
                "character": "Trending Lead",
                "order": 0,
                "profile_path": None,
            }
        ],
        "crew": [
            {
                "id": 557002,
                "name": "Trending Credits Director",
                "job": "Director",
                "profile_path": None,
            }
        ],
    }

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
            new=AsyncMock(return_value=_tmdb_movie_detail(9201, "Trending Credits Movie")),
        ),
        patch(
            "backlogg.movies.service._tmdb.get_movie_credits",
            new=AsyncMock(return_value=credits_data),
        ),
    ):
        response = await client.get("/v1/trending?type=movie")

    assert response.status_code == 200
    movie = await movies_repo.get_movie_by_slug(db, "trending-credits-movie-2023")
    assert movie is not None
    persisted_credits = await get_credits_for_item(db, "MOVIE", movie.id)
    roles = {c.role for c in persisted_credits}
    assert "ACTOR" in roles
    assert "DIRECTOR" in roles


async def test_trending_persists_series_credits_and_creators_for_new_series(client, db):
    """A series ingested via trending gets its cast+creators persisted too, not just the item row.

    Regression coverage for the reported bug (House of the Dragon showing
    "No credit information available" despite TMDB having cast data).
    """
    raw_series = _raw_series(tmdb_id=9202, slug_title="Trending Credits Series")
    series_detail = _tmdb_series_detail(9202, "Trending Credits Series")
    series_detail["created_by"] = [
        {"id": 557003, "name": "Trending Credits Creator", "profile_path": None}
    ]
    credits_data = {
        "cast": [
            {
                "id": 557004,
                "name": "Trending Credits Series Actor",
                "character": "Trending Series Lead",
                "order": 0,
                "profile_path": None,
            }
        ],
        "crew": [],
    }

    with (
        patch(
            "backlogg.trending.service._movies_tmdb.get_trending_movies",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_trending_series",
            new=AsyncMock(return_value=[raw_series]),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_series_detail",
            new=AsyncMock(return_value=series_detail),
        ),
        patch(
            "backlogg.series.service._tmdb.get_series_credits",
            new=AsyncMock(return_value=credits_data),
        ),
    ):
        response = await client.get("/v1/trending?type=series")

    assert response.status_code == 200
    series = await series_repo.get_series_by_slug(db, "trending-credits-series-2022")
    assert series is not None
    persisted_credits = await get_credits_for_item(db, "SERIES", series.id)
    roles = {c.role for c in persisted_credits}
    assert "ACTOR" in roles
    assert "CREATOR" in roles
