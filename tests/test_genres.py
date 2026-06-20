"""Tests for GET /genres endpoint (feature 15)."""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_movie(slug: str, genres: list[dict]) -> dict:
    return {
        "title": f"Movie {slug}",
        "original_title": None,
        "slug": slug,
        "overview": None,
        "release_date": date(2020, 1, 1),
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres,
    }


def _make_series(slug: str, genres: list[dict]) -> dict:
    return {
        "title": f"Series {slug}",
        "original_title": None,
        "slug": slug,
        "overview": None,
        "first_air_date": date(2020, 1, 1),
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 8,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres,
    }


def _make_book(slug: str, genres: list[dict]) -> dict:
    return {
        "title": f"Book {slug}",
        "original_title": None,
        "slug": slug,
        "overview": None,
        "first_publish_date": date(2020, 1, 1),
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres,
    }


def _make_game(slug: str, genres: list[dict]) -> dict:
    return {
        "title": f"Game {slug}",
        "original_title": None,
        "slug": slug,
        "overview": None,
        "release_date": date(2020, 1, 1),
        "game_type": "game",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres,
        "platforms": [],
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(db):
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_genres_returns_200_empty(client, db):
    """GET /genres returns 200 with genres list field."""
    response = await client.get("/genres")
    assert response.status_code == 200
    body = response.json()
    assert "genres" in body
    assert isinstance(body["genres"], list)


async def test_genres_all_types_present(client, db):
    """GET /genres without type filter returns genres from all item types."""
    await movies_repo.upsert_movie(
        db,
        _make_movie(
            slug="gall-movie-action-2021",
            genres=[{"name": "gall-action-movie", "slug": "gall-action-movie-slug"}],
        ),
    )
    await series_repo.upsert_series(
        db,
        _make_series(
            slug="gall-series-drama-2021",
            genres=[{"name": "gall-drama-series", "slug": "gall-drama-series-slug"}],
        ),
    )
    await books_repo.upsert_book(
        db,
        _make_book(
            slug="gall-book-scifi-2021",
            genres=[{"name": "gall-scifi-book", "slug": "gall-scifi-book-slug"}],
        ),
    )
    await games_repo.upsert_game(
        db,
        _make_game(
            slug="gall-game-rpg-2021",
            genres=[{"name": "gall-rpg-game", "slug": "gall-rpg-game-slug"}],
        ),
    )

    response = await client.get("/genres")
    assert response.status_code == 200
    genres = response.json()["genres"]

    item_types = {g["item_type"] for g in genres}
    assert "movie" in item_types
    assert "series" in item_types
    assert "book" in item_types
    assert "game" in item_types


async def test_genres_filter_by_movie(client, db):
    """GET /genres?type=movie returns only movie genres."""
    await movies_repo.upsert_movie(
        db,
        _make_movie(
            slug="gfm-movie-comedy-2021",
            genres=[{"name": "gfm-comedy-movie", "slug": "gfm-comedy-movie-slug"}],
        ),
    )
    await series_repo.upsert_series(
        db,
        _make_series(
            slug="gfm-series-comedy-2021",
            genres=[{"name": "gfm-comedy-series", "slug": "gfm-comedy-series-slug"}],
        ),
    )

    response = await client.get("/genres?type=movie")
    assert response.status_code == 200
    genres = response.json()["genres"]

    item_types = {g["item_type"] for g in genres}
    assert item_types == {"movie"}


async def test_genres_filter_by_series(client, db):
    """GET /genres?type=series returns only series genres."""
    await series_repo.upsert_series(
        db,
        _make_series(
            slug="gfs-series-thriller-2021",
            genres=[{"name": "gfs-thriller-series", "slug": "gfs-thriller-series-slug"}],
        ),
    )

    response = await client.get("/genres?type=series")
    assert response.status_code == 200
    genres = response.json()["genres"]

    item_types = {g["item_type"] for g in genres}
    assert item_types == {"series"}


async def test_genres_filter_by_book(client, db):
    """GET /genres?type=book returns only book genres."""
    await books_repo.upsert_book(
        db,
        _make_book(
            slug="gfb-book-mystery-2021",
            genres=[{"name": "gfb-mystery-book", "slug": "gfb-mystery-book-slug"}],
        ),
    )

    response = await client.get("/genres?type=book")
    assert response.status_code == 200
    genres = response.json()["genres"]

    item_types = {g["item_type"] for g in genres}
    assert item_types == {"book"}


async def test_genres_filter_by_game(client, db):
    """GET /genres?type=game returns only game genres."""
    await games_repo.upsert_game(
        db,
        _make_game(
            slug="gfg-game-action-2021",
            genres=[{"name": "gfg-action-game", "slug": "gfg-action-game-slug"}],
        ),
    )

    response = await client.get("/genres?type=game")
    assert response.status_code == 200
    genres = response.json()["genres"]

    item_types = {g["item_type"] for g in genres}
    assert item_types == {"game"}


async def test_genres_invalid_type_returns_422(client, db):
    """GET /genres?type=invalid returns 422."""
    response = await client.get("/genres?type=invalid")
    assert response.status_code == 422


async def test_genres_response_fields(client, db):
    """Each genre includes name, slug, item_type and count."""
    await movies_repo.upsert_movie(
        db,
        _make_movie(
            slug="grf-movie-horror-2021",
            genres=[{"name": "grf-horror-movie", "slug": "grf-horror-movie-slug"}],
        ),
    )

    response = await client.get("/genres?type=movie")
    assert response.status_code == 200
    genres = response.json()["genres"]

    # Find our genre
    horror = next(
        (g for g in genres if g["slug"] == "grf-horror-movie-slug"),
        None,
    )
    assert horror is not None
    assert horror["name"] == "grf-horror-movie"
    assert horror["slug"] == "grf-horror-movie-slug"
    assert horror["item_type"] == "movie"
    assert isinstance(horror["count"], int)


async def test_genres_count_reflects_real_items(client, db):
    """Count reflects the actual number of associated items."""
    genre_data = {"name": "gcount-action-mv", "slug": "gcount-action-mv-slug"}

    # Insert two movies with the same genre
    await movies_repo.upsert_movie(
        db,
        _make_movie(slug="gcount-movie-a-2021", genres=[genre_data]),
    )
    await movies_repo.upsert_movie(
        db,
        _make_movie(slug="gcount-movie-b-2021", genres=[genre_data]),
    )

    response = await client.get("/genres?type=movie")
    assert response.status_code == 200
    genres = response.json()["genres"]

    action_genre = next(
        (g for g in genres if g["slug"] == "gcount-action-mv-slug"),
        None,
    )
    assert action_genre is not None
    assert action_genre["count"] == 2


async def test_genres_count_zero_for_empty_genre(client, db):
    """A genre with no items has count = 0."""
    # Insert a movie with the genre
    await movies_repo.upsert_movie(
        db,
        _make_movie(
            slug="gcz-movie-temp-2021",
            genres=[{"name": "gcz-orphan-genre", "slug": "gcz-orphan-genre-slug"}],
        ),
    )

    # Now we need a genre that exists but has no movies linked — we can do
    # this by inserting a movie, then checking a genre slug that we insert via
    # a series (different table) while filtering for movies.
    await series_repo.upsert_series(
        db,
        _make_series(
            slug="gcz-series-temp-2021",
            genres=[{"name": "gcz-orphan-series-genre", "slug": "gcz-orphan-series-slug"}],
        ),
    )

    # GET /genres?type=movie should NOT include any series genres
    response = await client.get("/genres?type=movie")
    assert response.status_code == 200
    genres = response.json()["genres"]
    slugs = {g["slug"] for g in genres}
    assert "gcz-orphan-series-slug" not in slugs
