"""Endpoint tests for catalog search filters (feature 50).

Covers ``GET /v1/movies|series|books|games`` with the new ``search``/
``date_from``/``date_to``/``rating_internal_min``/``rating_internal_max``/
``rating_external_min``/``rating_external_max`` query params: happy paths
combining the new filters with each other and with the pre-existing
``genre``/``sort``/``page``/``limit`` (feature 14), the response contract
staying ``items``/``total``/``page``/``limit``, and 422 on invalid input
(bad date format, ``date_from > date_to``, ``*_min > *_max``) — for all 4
content types.

Also covers the response-caching interaction (feature 39): listings never
carry an ``ETag`` (only detail reads do — see ``core/http_cache.py``), and a
shared/downstream HTTP cache keys a GET request on the full URL including its
query string, so two requests with different filter query params are always
distinct cache entries — nothing to key manually here.
"""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo


@pytest_asyncio.fixture
async def client(db):
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _seed_movie(db, slug: str, title: str, rel: date, rext: float, rint: float) -> None:
    await movies_repo.upsert_movie(
        db,
        {
            "title": title,
            "original_title": title,
            "slug": slug,
            "overview": "x",
            "release_date": rel,
            "runtime": 100,
            "original_language": "en",
            "poster_url": None,
            "backdrop_url": None,
            "budget": None,
            "revenue": None,
            "status": "Released",
            "rating_external": rext,
            "rating_count_external": 10,
            "rating_internal": rint,
            "rating_count_internal": 3,
            "last_synced_at": datetime.now(UTC),
            "genres": [],
        },
    )


async def _seed_series(db, slug: str, title: str, rel: date, rext: float, rint: float) -> None:
    await series_repo.upsert_series(
        db,
        {
            "title": title,
            "original_title": title,
            "slug": slug,
            "overview": "x",
            "first_air_date": rel,
            "last_air_date": None,
            "number_of_seasons": 1,
            "number_of_episodes": 6,
            "status": "Ended",
            "original_language": "en",
            "poster_url": None,
            "backdrop_url": None,
            "rating_external": rext,
            "rating_count_external": 10,
            "rating_internal": rint,
            "rating_count_internal": 3,
            "last_synced_at": datetime.now(UTC),
            "genres": [],
        },
    )


async def _seed_book(db, slug: str, title: str, rel: date, rext: float, rint: float) -> None:
    await books_repo.upsert_book(
        db,
        {
            "title": title,
            "original_title": None,
            "slug": slug,
            "overview": "x",
            "first_publish_date": rel,
            "original_language": "en",
            "poster_url": None,
            "rating_external": rext,
            "rating_count_external": 10,
            "rating_internal": rint,
            "rating_count_internal": 3,
            "last_synced_at": datetime.now(UTC),
            "genres": [],
        },
    )


async def _seed_game(db, slug: str, title: str, rel: date, rext: float, rint: float) -> None:
    await games_repo.upsert_game(
        db,
        {
            "title": title,
            "original_title": title,
            "slug": slug,
            "overview": "x",
            "release_date": rel,
            "game_type": "main_game",
            "original_language": None,
            "poster_url": None,
            "backdrop_url": None,
            "rating_external": rext,
            "rating_count_external": 10,
            "rating_internal": rint,
            "rating_count_internal": 3,
            "last_synced_at": datetime.now(UTC),
            "genres": [],
            "platforms": [],
            "companies": [],
        },
    )


# ── Happy paths: search, date range, rating range, response contract ────────


async def test_movies_search_filters_by_title_substring_case_insensitive(client, db):
    await _seed_movie(db, "csf-movie-dune-2021", "Dune", date(2021, 10, 22), 7.8, 4.2)
    await _seed_movie(db, "csf-movie-other-2021", "Some Other Film", date(2021, 1, 1), 6.0, 3.0)

    response = await client.get("/v1/movies?search=dUnE")
    assert response.status_code == 200
    body = response.json()
    slugs = [item["slug"] for item in body["items"]]
    assert "csf-movie-dune-2021" in slugs
    assert "csf-movie-other-2021" not in slugs
    # Response contract unchanged (feature 14).
    assert set(body.keys()) == {"items", "total", "page", "limit"}


async def test_series_date_range_filters_first_air_date_inclusive(client, db):
    await _seed_series(db, "csf-series-in-2020", "In Range Series", date(2020, 6, 1), 7.0, 4.0)
    await _seed_series(db, "csf-series-out-2015", "Out Of Range Series", date(2015, 6, 1), 7.0, 4.0)

    response = await client.get("/v1/series?date_from=2020-01-01&date_to=2021-12-31")
    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()["items"]]
    assert "csf-series-in-2020" in slugs
    assert "csf-series-out-2015" not in slugs


async def test_books_rating_range_filters_are_combinable_with_genre_sort_page_limit(client, db):
    await books_repo.upsert_book(
        db,
        {
            "title": "High Rated Book",
            "original_title": None,
            "slug": "csf-book-high-2010",
            "overview": "x",
            "first_publish_date": date(2010, 1, 1),
            "original_language": "en",
            "poster_url": None,
            "rating_external": 9.0,
            "rating_count_external": 10,
            "rating_internal": 4.8,
            "rating_count_internal": 3,
            "last_synced_at": datetime.now(UTC),
            "genres": [{"name": "csf-book-genre", "slug": "csf-book-genre"}],
        },
    )
    await books_repo.upsert_book(
        db,
        {
            "title": "Low Rated Book",
            "original_title": None,
            "slug": "csf-book-low-2010",
            "overview": "x",
            "first_publish_date": date(2010, 1, 1),
            "original_language": "en",
            "poster_url": None,
            "rating_external": 3.0,
            "rating_count_external": 10,
            "rating_internal": 1.0,
            "rating_count_internal": 3,
            "last_synced_at": datetime.now(UTC),
            "genres": [{"name": "csf-book-genre", "slug": "csf-book-genre"}],
        },
    )

    response = await client.get(
        "/v1/books"
        "?genre=csf-book-genre&sort=rating_desc&page=1&limit=10"
        "&rating_internal_min=4.0&rating_internal_max=5.0"
        "&rating_external_min=8.0&rating_external_max=10.0"
    )
    assert response.status_code == 200
    body = response.json()
    slugs = [item["slug"] for item in body["items"]]
    assert slugs == ["csf-book-high-2010"]
    assert body["page"] == 1
    assert body["limit"] == 10


async def test_games_all_new_filters_combined(client, db):
    await _seed_game(db, "csf-game-doom-1993", "Doom", date(1993, 12, 10), 8.5, 4.5)
    await _seed_game(db, "csf-game-other-2000", "Other Game", date(2000, 1, 1), 5.0, 2.0)

    response = await client.get(
        "/v1/games"
        "?search=doom&date_from=1990-01-01&date_to=1999-12-31"
        "&rating_internal_min=4.0&rating_internal_max=5.0"
        "&rating_external_min=8.0&rating_external_max=10.0"
    )
    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()["items"]]
    assert slugs == ["csf-game-doom-1993"]


# ── 422 on invalid input, for all 4 types ────────────────────────────────────


async def test_movies_invalid_date_format_returns_422(client, db):
    response = await client.get("/v1/movies?date_from=not-a-date")
    assert response.status_code == 422


async def test_movies_date_from_after_date_to_returns_422(client, db):
    response = await client.get("/v1/movies?date_from=2021-12-31&date_to=2021-01-01")
    assert response.status_code == 422


async def test_movies_rating_internal_min_greater_than_max_returns_422(client, db):
    response = await client.get("/v1/movies?rating_internal_min=4&rating_internal_max=2")
    assert response.status_code == 422


async def test_movies_rating_external_min_greater_than_max_returns_422(client, db):
    response = await client.get("/v1/movies?rating_external_min=9&rating_external_max=3")
    assert response.status_code == 422


async def test_series_date_from_after_date_to_returns_422(client, db):
    response = await client.get("/v1/series?date_from=2021-12-31&date_to=2021-01-01")
    assert response.status_code == 422


async def test_series_rating_min_greater_than_max_returns_422(client, db):
    response = await client.get("/v1/series?rating_internal_min=4&rating_internal_max=1")
    assert response.status_code == 422


async def test_books_invalid_date_format_returns_422(client, db):
    response = await client.get("/v1/books?date_to=31-12-2021")
    assert response.status_code == 422


async def test_books_rating_external_min_greater_than_max_returns_422(client, db):
    response = await client.get("/v1/books?rating_external_min=9&rating_external_max=1")
    assert response.status_code == 422


async def test_games_date_from_after_date_to_returns_422(client, db):
    response = await client.get("/v1/games?date_from=2021-12-31&date_to=2021-01-01")
    assert response.status_code == 422


async def test_games_rating_internal_min_greater_than_max_returns_422(client, db):
    response = await client.get("/v1/games?rating_internal_min=4&rating_internal_max=1")
    assert response.status_code == 422


# ── Caching interaction (feature 39) ─────────────────────────────────────────


async def test_listing_cache_control_is_shared_across_filter_combinations_no_etag(client, db):
    """Listings never carry an ETag; distinct filters differ only by URL/body.

    Feature 39 gives catalog listings a plain ``Cache-Control: public,
    max-age=...`` with no ``ETag`` (only detail reads get one — see
    ``core/http_cache.py``). Since the cache key any HTTP cache uses for a GET
    is the full request URL (path + query string), two different filter
    combinations are already distinct entries without any code change here —
    this test pins that behaviour so a future change to the caching layer
    cannot silently start collapsing different filters into one entry.
    """
    await _seed_movie(db, "csf-cache-a-2021", "Cache Filter A", date(2021, 1, 1), 5.0, 3.0)
    await _seed_movie(db, "csf-cache-b-2021", "Cache Filter B", date(2021, 1, 1), 9.0, 5.0)

    unfiltered = await client.get("/v1/movies")
    filtered = await client.get("/v1/movies?rating_internal_min=4.5")

    assert unfiltered.status_code == 200
    assert filtered.status_code == 200
    assert "etag" not in unfiltered.headers
    assert "etag" not in filtered.headers
    assert unfiltered.headers["cache-control"] == filtered.headers["cache-control"]
    assert unfiltered.json() != filtered.json()
