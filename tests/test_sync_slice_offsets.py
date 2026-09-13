"""What outlived feature 24 (sync_slice_cursor).

⚠️ **No sync job walks a listing by offset any more, and the cursor table is
gone.**  Movies and series left the cursor in feature 86, games in feature 90
and books in issue #27; all four build their work list from the local catalog
(the ``seed_targets`` difference, the ``last_synced_at`` rotation, or both),
and ``sync_cursors`` was dropped once the last reader left.  The job-slice
cases this file was written for went with it, and what is left is:

- the **offset support of the adapters** whose ranking methods still exist
  (``get_top_movies``/``get_top_series``/``get_top_games``): documented
  clients of ``/movie/popular``, ``/tv/popular`` and IGDB's ``rating_count``
  ranking, even though no seeding path calls them.  Open Library's equivalent
  went with ``get_popular_books``.
- one **idempotency** case: running the same slice twice must not duplicate a
  row, which is now guaranteed by the refresh rotation instead of by a cursor.

That no job has a cursor left is asserted where each job lives
(``tests/test_tmdb_discover_seeding.py``, ``tests/test_igdb_targets_seeding.py``
and ``tests/test_sync_books_refresh.py``); that the table itself is gone, in
``tests/test_drop_sync_cursors.py``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import func, select

from backlogg.games.adapters.igdb import IGDBClient
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.models import Movie
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import SeedTargetRow, upsert_seed_targets
from backlogg.series.adapters.tmdb import TMDBSeriesClient

# ── Adapters accept offset ────────────────────────────────────────────────────


def _tmdb_page_response(start: int, total_pages: int = 500) -> MagicMock:
    """A TMDB page of 20 items with sequential ids starting at ``start``."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"id": i} for i in range(start, start + 20)],
        "total_pages": total_pages,
    }
    response.raise_for_status = MagicMock()
    return response


async def test_tmdb_movies_offset_translates_to_pages():
    """offset=30 → page 2 requested; the first offset % 20 items are dropped."""
    client = TMDBClient()
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_tmdb_page_response(start=20),
    ) as mock_get:
        results = await client.get_top_movies(limit=10, offset=30)

    mock_get.assert_awaited_once()
    assert mock_get.call_args.kwargs["params"] == {"page": 2}
    assert [r["id"] for r in results] == list(range(30, 40))


async def test_tmdb_movies_beyond_page_500_returns_empty():
    """TMDB caps pagination at page 500 — offsets beyond it return []."""
    client = TMDBClient()
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        results = await client.get_top_movies(limit=10, offset=10000)

    mock_get.assert_not_awaited()
    assert results == []


async def test_tmdb_series_offset_translates_to_pages():
    """offset=45 → page 3 requested; the first 5 items are dropped."""
    client = TMDBSeriesClient()
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_tmdb_page_response(start=40),
    ) as mock_get:
        results = await client.get_top_series(limit=15, offset=45)

    mock_get.assert_awaited_once()
    assert mock_get.call_args.kwargs["params"] == {"page": 3}
    assert [r["id"] for r in results] == list(range(45, 60))


async def test_igdb_query_includes_offset_clause():
    """IGDB receives a native ``offset N;`` clause in the query body."""
    client = IGDBClient()
    with patch.object(client, "_post", new_callable=AsyncMock, return_value=[]) as mock_post:
        await client.get_top_games(limit=50, offset=200)

    mock_post.assert_awaited_once()
    body = mock_post.call_args.args[1]
    assert " limit 50;" in body
    assert " offset 200;" in body


# ── Idempotency of re-running the same slice (real test DB) ──────────────────


async def test_rerunning_the_same_movie_slice_is_idempotent(db, monkeypatch):
    """Re-executing the same movie slice does not duplicate items.

    Rewritten for feature 86: there is no cursor to wrap any more, so what
    makes the second run process the same item is the refresh rotation — once
    the single target is hydrated nothing is pending, and the slice is filled
    with the least recently synced movie, which is that very item.  The upsert
    must make that a no-op.
    """
    await upsert_seed_targets(
        db,
        [SeedTargetRow("MOVIE", "TMDB", "97701", vote_count=42, release_year=2023)],
    )
    await db.commit()

    movie_raw = {
        "id": 97701,
        "title": "Slice Cursor Test Movie",
        "original_title": "Slice Cursor Test Movie",
        "overview": "A movie for testing slice idempotency.",
        "release_date": "2023-02-01",
        "runtime": 100,
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 6.5,
        "vote_count": 42,
        "genres": [],
        "credits": {"cast": [], "crew": []},
    }

    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_movie_detail",
            new_callable=AsyncMock,
            return_value=movie_raw,
        ) as mock_detail,
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        result1 = await sync_jobs.sync_movies(slice_size=5)
        result2 = await sync_jobs.sync_movies(slice_size=5)

    # First run works the pending target, second one the refresh rotation.
    assert result1["refreshed"] == 0
    assert result2["refreshed"] == 1
    assert result1["pending"] == 0
    assert result2["pending"] == 0
    assert mock_detail.await_count == 2

    # No duplicates
    result = await db.execute(select(func.count()).where(Movie.title == "Slice Cursor Test Movie"))
    assert result.scalar_one() == 1
