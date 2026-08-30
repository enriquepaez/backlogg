"""Tests for POST /admin/sync/{type} endpoint.

Mocks all external API clients so no real network calls are made.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from backlogg.main import app
from backlogg.movies.models import Movie
from backlogg.scheduler import jobs as sync_jobs

_SYNC_RESULT = {"synced": 5, "errors": 0, "offset": 0, "duration_s": 1.2}
_VALID_KEY = "test-admin-secret"


def _cursor_patches(offset: int = 0):
    """Patches for the sync-cursor repository: cursor at ``offset``, writes mocked."""
    return (
        patch(
            "backlogg.scheduler.jobs.get_sync_offset",
            new_callable=AsyncMock,
            return_value=offset,
        ),
        patch(
            "backlogg.scheduler.jobs.set_sync_offset",
            new_callable=AsyncMock,
        ),
    )


@pytest_asyncio.fixture
async def client():
    """AsyncClient wired to the FastAPI app with a valid API key configured."""
    with patch("backlogg.admin.auth.settings") as mock_settings:
        mock_settings.ADMIN_API_KEY = _VALID_KEY
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


# ── Happy paths ───────────────────────────────────────────────────────────────


async def test_sync_movie_returns_200(client):
    """POST /admin/sync/movie runs sync synchronously and returns 200 with result."""
    mock_handler = AsyncMock(return_value=_SYNC_RESULT)
    with patch.dict("backlogg.admin.router._SYNC_HANDLERS", {"movie": mock_handler}):
        response = await client.post("/v1/admin/sync/movie", headers={"X-API-Key": _VALID_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "movie"
    assert body["synced"] == 5
    assert body["errors"] == 0
    assert body["offset"] == 0
    assert body["duration_s"] == 1.2


async def test_sync_series_returns_200(client):
    """POST /admin/sync/series runs sync synchronously and returns 200 with result."""
    mock_handler = AsyncMock(return_value=_SYNC_RESULT)
    with patch.dict("backlogg.admin.router._SYNC_HANDLERS", {"series": mock_handler}):
        response = await client.post("/v1/admin/sync/series", headers={"X-API-Key": _VALID_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "series"
    assert body["synced"] == 5
    assert body["errors"] == 0
    assert body["offset"] == 0
    assert body["duration_s"] == 1.2


async def test_sync_book_returns_200(client):
    """POST /admin/sync/book runs sync synchronously and returns 200 with result."""
    mock_handler = AsyncMock(return_value=_SYNC_RESULT)
    with patch.dict("backlogg.admin.router._SYNC_HANDLERS", {"book": mock_handler}):
        response = await client.post("/v1/admin/sync/book", headers={"X-API-Key": _VALID_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "book"
    assert body["synced"] == 5
    assert body["errors"] == 0
    assert body["offset"] == 0
    assert body["duration_s"] == 1.2


async def test_sync_game_returns_200(client):
    """POST /admin/sync/game runs sync synchronously and returns 200 with result."""
    mock_handler = AsyncMock(return_value=_SYNC_RESULT)
    with patch.dict("backlogg.admin.router._SYNC_HANDLERS", {"game": mock_handler}):
        response = await client.post("/v1/admin/sync/game", headers={"X-API-Key": _VALID_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "game"
    assert body["synced"] == 5
    assert body["errors"] == 0
    assert body["offset"] == 0
    assert body["duration_s"] == 1.2


# ── Validation ────────────────────────────────────────────────────────────────


async def test_sync_unknown_type_returns_422(client):
    """POST /admin/sync/unknown returns 422 (unprocessable entity)."""
    response = await client.post("/v1/admin/sync/unknown", headers={"X-API-Key": _VALID_KEY})
    assert response.status_code == 422


async def test_sync_empty_type_returns_422(client):
    """POST /admin/sync/ (no type) returns 404 (route not matched)."""
    response = await client.post("/v1/admin/sync/", headers={"X-API-Key": _VALID_KEY})
    # FastAPI returns 404 for missing path segment, not 422
    assert response.status_code in (404, 422)


# ── Error isolation ───────────────────────────────────────────────────────────


async def test_sync_movies_error_does_not_affect_sync_series():
    """A failure in sync_movies does not prevent sync_series from running.

    This validates acceptance criterion C19: errors are swallowed per job.
    Both jobs must complete without raising even when the external API is down.
    """
    get_cursor, set_cursor = _cursor_patches()
    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_top_movies",
            new_callable=AsyncMock,
            side_effect=RuntimeError("TMDB movies is down"),
        ),
        patch.object(
            sync_jobs._tmdb_series,
            "get_top_series",
            new_callable=AsyncMock,
            side_effect=RuntimeError("TMDB series is down"),
        ),
        get_cursor,
        set_cursor,
    ):
        # Neither call must raise — each job swallows its own exceptions
        result_movies = await sync_jobs.sync_movies()
        result_series = await sync_jobs.sync_series()

    # When the initial fetch fails the job returns errors=1
    assert result_movies["synced"] == 0
    assert result_movies["errors"] == 1
    assert result_series["synced"] == 0
    assert result_series["errors"] == 1


async def test_sync_movies_job_catches_external_error():
    """sync_movies logs and returns a result dict when the external API raises."""
    get_cursor, set_cursor = _cursor_patches()
    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_top_movies",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ),
        get_cursor,
        set_cursor,
    ):
        result = await sync_jobs.sync_movies()

    assert result["synced"] == 0
    assert result["errors"] == 1
    assert "duration_s" in result


async def test_sync_games_job_catches_external_error():
    """sync_games logs and returns a result dict when IGDB raises."""
    get_cursor, set_cursor = _cursor_patches()
    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_top_games",
            new_callable=AsyncMock,
            side_effect=RuntimeError("igdb down"),
        ),
        get_cursor,
        set_cursor,
    ):
        result = await sync_jobs.sync_games()

    assert result["synced"] == 0
    assert result["errors"] == 1
    assert "duration_s" in result


async def test_sync_books_job_catches_external_error():
    """sync_books logs and returns a result dict when Open Library raises."""
    get_cursor, set_cursor = _cursor_patches()
    with (
        patch.object(
            sync_jobs._ol_client,
            "get_popular_books",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ol down"),
        ),
        get_cursor,
        set_cursor,
    ):
        result = await sync_jobs.sync_books()

    assert result["synced"] == 0
    assert result["errors"] == 1
    assert "duration_s" in result


async def test_sync_series_job_catches_external_error():
    """sync_series logs and returns a result dict when TMDB raises."""
    get_cursor, set_cursor = _cursor_patches()
    with (
        patch.object(
            sync_jobs._tmdb_series,
            "get_top_series",
            new_callable=AsyncMock,
            side_effect=RuntimeError("tmdb down"),
        ),
        get_cursor,
        set_cursor,
    ):
        result = await sync_jobs.sync_series()

    assert result["synced"] == 0
    assert result["errors"] == 1
    assert "duration_s" in result


# ── Idempotency (upsert) ──────────────────────────────────────────────────────


async def test_sync_movies_is_idempotent(db):
    """Running sync_movies twice with the same data does not create duplicates.

    We mock the TMDB adapter to return a single deterministic movie and verify
    that after two calls the DB still has exactly one row for that slug.
    """
    movie_raw = {
        "id": 99901,
        "title": "Idempotent Test Movie",
        "original_title": "Idempotent Test Movie",
        "overview": "A movie for testing idempotency.",
        "release_date": "2020-01-01",
        "runtime": 90,
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 7.0,
        "vote_count": 100,
        "genres": [],
    }

    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_top_movies",
            new_callable=AsyncMock,
            return_value=[{"id": 99901}],
        ),
        patch.object(
            sync_jobs._tmdb_movies,
            "get_movie_detail",
            new_callable=AsyncMock,
            return_value=movie_raw,
        ),
        patch.object(
            sync_jobs,
            "_refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch(
            "backlogg.scheduler.jobs._persist_movie_people",
            new_callable=AsyncMock,
        ),
        # Use the test DB session factory so writes land in the test DB
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        # Wire factory to yield the test session
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        result1 = await sync_jobs.sync_movies()
        result2 = await sync_jobs.sync_movies()

    result = await db.execute(select(func.count()).where(Movie.title == "Idempotent Test Movie"))
    count = result.scalar_one()
    assert count == 1, f"Expected 1 row, got {count} — upsert is not idempotent"

    # Both runs must report synced=1 (the upsert counts as success each time)
    assert result1["synced"] == 1
    assert result2["synced"] == 1


async def test_sync_books_calls_get_work_detail_for_authors():
    """sync_books must call get_work_detail to fetch authors for each book with a work_id."""
    popular_raw = [
        {
            "key": "/works/OL123W",
            "title": "Test Book",
            "first_publish_year": 2020,
            "cover_i": 12345,
            "author_name": ["Test Author"],
        }
    ]
    work_detail_data = {
        "title": "Test Book",
        "authors": [],
    }
    get_cursor, set_cursor = _cursor_patches()
    with (
        get_cursor,
        set_cursor,
        patch.object(
            sync_jobs._ol_client,
            "get_popular_books",
            new_callable=AsyncMock,
            return_value=popular_raw,
        ),
        patch.object(
            sync_jobs._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            return_value=work_detail_data,
        ) as mock_work_detail,
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
        ) as mock_factory,
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch(
            "backlogg.scheduler.jobs._persist_book_authors",
            new_callable=AsyncMock,
        ) as mock_persist_authors,
    ):
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        with (
            patch(
                "backlogg.books.repository.upsert_book",
                new_callable=AsyncMock,
            ) as mock_upsert,
            patch(
                "backlogg.scheduler.jobs.upsert_external_id",
                new_callable=AsyncMock,
            ),
        ):
            mock_book = MagicMock()
            mock_book.id = 1
            mock_upsert.return_value = mock_book
            result = await sync_jobs.sync_books()

    mock_work_detail.assert_called_once_with("OL123W")
    mock_persist_authors.assert_called_once()
    assert result["synced"] == 1
    assert result["errors"] == 0


async def test_sync_movies_calls_persist_movie_people():
    """sync_movies must call _persist_movie_people once per successfully upserted movie."""
    movie_raw = {
        "id": 88801,
        "title": "Credits Test Movie",
        "original_title": "Credits Test Movie",
        "overview": "A movie for testing people persistence.",
        "release_date": "2021-05-01",
        "runtime": 110,
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 8.0,
        "vote_count": 200,
        "genres": [],
    }

    get_cursor, set_cursor = _cursor_patches()
    with (
        get_cursor,
        set_cursor,
        patch.object(
            sync_jobs._tmdb_movies,
            "get_top_movies",
            new_callable=AsyncMock,
            return_value=[{"id": 88801}],
        ),
        patch.object(
            sync_jobs._tmdb_movies,
            "get_movie_detail",
            new_callable=AsyncMock,
            return_value=movie_raw,
        ),
        patch(
            "backlogg.scheduler.jobs._persist_movie_people",
            new_callable=AsyncMock,
        ) as mock_persist_people,
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        with (
            patch(
                "backlogg.movies.repository.upsert_movie",
                new_callable=AsyncMock,
            ) as mock_upsert,
            patch(
                "backlogg.scheduler.jobs.upsert_external_id",
                new_callable=AsyncMock,
            ),
        ):
            mock_movie = MagicMock()
            mock_movie.id = 10
            mock_upsert.return_value = mock_movie
            result = await sync_jobs.sync_movies()

    mock_persist_people.assert_called_once()
    call_args = mock_persist_people.call_args
    assert call_args.args[2] == 88801  # tmdb_id passed correctly
    assert result["synced"] == 1
    assert result["errors"] == 0


async def test_sync_movies_persist_people_failure_does_not_increment_errors():
    """If _persist_movie_people raises, errors counter stays 0 and sync continues."""
    movie_raw = {
        "id": 88802,
        "title": "Credits Failure Movie",
        "original_title": "Credits Failure Movie",
        "overview": "Testing graceful degradation.",
        "release_date": "2022-03-15",
        "runtime": 95,
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 7.5,
        "vote_count": 50,
        "genres": [],
    }

    get_cursor, set_cursor = _cursor_patches()
    with (
        get_cursor,
        set_cursor,
        patch.object(
            sync_jobs._tmdb_movies,
            "get_top_movies",
            new_callable=AsyncMock,
            return_value=[{"id": 88802}],
        ),
        patch.object(
            sync_jobs._tmdb_movies,
            "get_movie_detail",
            new_callable=AsyncMock,
            return_value=movie_raw,
        ),
        patch(
            "backlogg.scheduler.jobs._persist_movie_people",
            new_callable=AsyncMock,
            side_effect=RuntimeError("credits API down"),
        ),
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        # expunge_all is a sync method on AsyncSession — the job calls it
        # after the per-item rollback that follows the people failure.
        mock_session.expunge_all = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        with (
            patch(
                "backlogg.movies.repository.upsert_movie",
                new_callable=AsyncMock,
            ) as mock_upsert,
            patch(
                "backlogg.scheduler.jobs.upsert_external_id",
                new_callable=AsyncMock,
            ),
        ):
            mock_movie = MagicMock()
            mock_movie.id = 11
            mock_upsert.return_value = mock_movie
            result = await sync_jobs.sync_movies()

    # The upsert succeeded, so synced=1 even though people persistence failed
    assert result["synced"] == 1
    # errors must NOT be incremented by people persistence failure
    assert result["errors"] == 0
    # people_errors is the dedicated counter for this failure mode
    assert result["people_errors"] == 1


async def test_sync_series_calls_persist_series_people_and_creators():
    """sync_series must call _persist_series_people and _persist_series_creators per item."""
    series_raw = {
        "id": 77701,
        "name": "Credits Test Series",
        "original_name": "Credits Test Series",
        "overview": "A series for testing people persistence.",
        "first_air_date": "2019-09-01",
        "last_air_date": "2023-06-01",
        "number_of_seasons": 3,
        "number_of_episodes": 30,
        "status": "Ended",
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 8.5,
        "vote_count": 500,
        "genres": [],
        "created_by": [{"id": 999, "name": "A Creator", "profile_path": None}],
    }

    get_cursor, set_cursor = _cursor_patches()
    with (
        get_cursor,
        set_cursor,
        patch.object(
            sync_jobs._tmdb_series,
            "get_top_series",
            new_callable=AsyncMock,
            return_value=[{"id": 77701}],
        ),
        patch.object(
            sync_jobs._tmdb_series,
            "get_series_detail",
            new_callable=AsyncMock,
            return_value=series_raw,
        ),
        patch(
            "backlogg.scheduler.jobs._persist_series_people",
            new_callable=AsyncMock,
        ) as mock_persist_people,
        patch(
            "backlogg.scheduler.jobs._persist_series_creators",
            new_callable=AsyncMock,
        ) as mock_persist_creators,
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        with (
            patch(
                "backlogg.series.repository.upsert_series",
                new_callable=AsyncMock,
            ) as mock_upsert,
            patch(
                "backlogg.scheduler.jobs.upsert_external_id",
                new_callable=AsyncMock,
            ),
        ):
            mock_series = MagicMock()
            mock_series.id = 20
            mock_upsert.return_value = mock_series
            result = await sync_jobs.sync_series()

    mock_persist_people.assert_called_once()
    mock_persist_creators.assert_called_once()
    assert result["synced"] == 1
    assert result["errors"] == 0


async def test_sync_series_persist_people_failure_does_not_increment_errors():
    """If _persist_series_people raises, errors stays 0 but people_errors increments."""
    series_raw = {
        "id": 77702,
        "name": "Credits Failure Series",
        "original_name": "Credits Failure Series",
        "overview": "Testing graceful degradation.",
        "first_air_date": "2018-01-01",
        "last_air_date": "2020-01-01",
        "number_of_seasons": 2,
        "number_of_episodes": 20,
        "status": "Ended",
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 6.5,
        "vote_count": 40,
        "genres": [],
        "created_by": [],
    }

    get_cursor, set_cursor = _cursor_patches()
    with (
        get_cursor,
        set_cursor,
        patch.object(
            sync_jobs._tmdb_series,
            "get_top_series",
            new_callable=AsyncMock,
            return_value=[{"id": 77702}],
        ),
        patch.object(
            sync_jobs._tmdb_series,
            "get_series_detail",
            new_callable=AsyncMock,
            return_value=series_raw,
        ),
        patch(
            "backlogg.scheduler.jobs._persist_series_people",
            new_callable=AsyncMock,
            side_effect=RuntimeError("credits API down"),
        ),
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.expunge_all = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        with (
            patch(
                "backlogg.series.repository.upsert_series",
                new_callable=AsyncMock,
            ) as mock_upsert,
            patch(
                "backlogg.scheduler.jobs.upsert_external_id",
                new_callable=AsyncMock,
            ),
        ):
            mock_series = MagicMock()
            mock_series.id = 21
            mock_upsert.return_value = mock_series
            result = await sync_jobs.sync_series()

    assert result["synced"] == 1
    assert result["errors"] == 0
    assert result["people_errors"] == 1


async def test_sync_books_persist_authors_failure_does_not_increment_errors():
    """If _persist_book_authors raises, errors stays 0 but people_errors increments."""
    popular_raw = [
        {
            "key": "/works/OL999W",
            "title": "Credits Failure Book",
            "first_publish_year": 2015,
            "cover_i": 54321,
            "author_name": ["Test Author"],
        }
    ]
    work_detail_data = {
        "title": "Credits Failure Book",
        "authors": [],
    }

    get_cursor, set_cursor = _cursor_patches()
    with (
        get_cursor,
        set_cursor,
        patch.object(
            sync_jobs._ol_client,
            "get_popular_books",
            new_callable=AsyncMock,
            return_value=popular_raw,
        ),
        patch.object(
            sync_jobs._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            return_value=work_detail_data,
        ),
        patch(
            "backlogg.scheduler.jobs._persist_book_authors",
            new_callable=AsyncMock,
            side_effect=RuntimeError("authors API down"),
        ),
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.expunge_all = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        with (
            patch(
                "backlogg.books.repository.upsert_book",
                new_callable=AsyncMock,
            ) as mock_upsert,
            patch(
                "backlogg.scheduler.jobs.upsert_external_id",
                new_callable=AsyncMock,
            ),
        ):
            mock_book = MagicMock()
            mock_book.id = 2
            mock_upsert.return_value = mock_book
            result = await sync_jobs.sync_books()

    assert result["synced"] == 1
    assert result["errors"] == 0
    assert result["people_errors"] == 1
