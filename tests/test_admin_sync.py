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


def _noop_create_task(coro):
    """Discard the coroutine cleanly to avoid 'coroutine never awaited' warnings."""
    coro.close()
    return MagicMock()


@pytest_asyncio.fixture
async def client():
    """AsyncClient wired to the FastAPI app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── Happy paths ───────────────────────────────────────────────────────────────


_CREATE_TASK = "backlogg.admin.router.asyncio.create_task"


async def test_sync_movie_returns_202(client):
    """POST /admin/sync/movie triggers sync and returns 202."""
    with patch(_CREATE_TASK, side_effect=_noop_create_task) as mock_task:
        response = await client.post("/admin/sync/movie")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "ok"
    assert body["type"] == "movie"
    mock_task.assert_called_once()


async def test_sync_series_returns_202(client):
    """POST /admin/sync/series triggers sync and returns 202."""
    with patch(_CREATE_TASK, side_effect=_noop_create_task) as mock_task:
        response = await client.post("/admin/sync/series")

    assert response.status_code == 202
    assert response.json()["type"] == "series"
    mock_task.assert_called_once()


async def test_sync_book_returns_202(client):
    """POST /admin/sync/book triggers sync and returns 202."""
    with patch(_CREATE_TASK, side_effect=_noop_create_task) as mock_task:
        response = await client.post("/admin/sync/book")

    assert response.status_code == 202
    assert response.json()["type"] == "book"
    mock_task.assert_called_once()


async def test_sync_game_returns_202(client):
    """POST /admin/sync/game triggers sync and returns 202."""
    with patch(_CREATE_TASK, side_effect=_noop_create_task) as mock_task:
        response = await client.post("/admin/sync/game")

    assert response.status_code == 202
    assert response.json()["type"] == "game"
    mock_task.assert_called_once()


# ── Validation ────────────────────────────────────────────────────────────────


async def test_sync_unknown_type_returns_422(client):
    """POST /admin/sync/unknown returns 422 (unprocessable entity)."""
    response = await client.post("/admin/sync/unknown")
    assert response.status_code == 422


async def test_sync_empty_type_returns_422(client):
    """POST /admin/sync/ (no type) returns 404 (route not matched)."""
    response = await client.post("/admin/sync/")
    # FastAPI returns 404 for missing path segment, not 422
    assert response.status_code in (404, 422)


# ── Error isolation ───────────────────────────────────────────────────────────


async def test_sync_movies_error_does_not_affect_sync_series():
    """A failure in sync_movies does not prevent sync_series from running.

    This validates acceptance criterion C19: errors are swallowed per job.
    Both jobs must complete without raising even when the external API is down.
    """
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
    ):
        # Neither call must raise — each job swallows its own exceptions
        await sync_jobs.sync_movies()
        await sync_jobs.sync_series()


async def test_sync_movies_job_catches_external_error():
    """sync_movies logs and returns when the external API raises."""
    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_top_movies",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ),
    ):
        # Must not raise — job catches all exceptions internally
        await sync_jobs.sync_movies()


async def test_sync_games_job_catches_external_error():
    """sync_games logs and returns when IGDB raises."""
    with patch.object(
        sync_jobs._igdb_client,
        "get_top_games",
        new_callable=AsyncMock,
        side_effect=RuntimeError("igdb down"),
    ):
        await sync_jobs.sync_games()


async def test_sync_books_job_catches_external_error():
    """sync_books logs and returns when Open Library raises."""
    with patch.object(
        sync_jobs._ol_client,
        "get_trending_books",
        new_callable=AsyncMock,
        side_effect=RuntimeError("ol down"),
    ):
        await sync_jobs.sync_books()


async def test_sync_series_job_catches_external_error():
    """sync_series logs and returns when TMDB raises."""
    with patch.object(
        sync_jobs._tmdb_series,
        "get_top_series",
        new_callable=AsyncMock,
        side_effect=RuntimeError("tmdb down"),
    ):
        await sync_jobs.sync_series()


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
        # Use the test DB session factory so writes land in the test DB
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        # Wire factory to yield the test session
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        await sync_jobs.sync_movies()
        await sync_jobs.sync_movies()

    result = await db.execute(select(func.count()).where(Movie.title == "Idempotent Test Movie"))
    count = result.scalar_one()
    assert count == 1, f"Expected 1 row, got {count} — upsert is not idempotent"
