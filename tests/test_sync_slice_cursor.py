"""Tests for feature 24 — sync_slice_cursor.

Covers:
- the sync-cursor repository against the real test database;
- the offset support in each external adapter (HTTP layer mocked);
- the slice logic in the cursor-driven sync jobs (adapters and cursor repo
  mocked): intermediate slice advances the cursor, final slice wraps to 0, and
  a short API response wraps to 0.

⚠️ Since feature 86 the cursor drives **books and games only**.  Movies and
series are hydrated from the ``seed_targets`` work list and never read or
write ``sync_cursors``, so the four job-slice cases below — which used to be
written against ``sync_movies`` — are now written against ``sync_games``: the
logic under test (``_read_slice``/``_next_offset``) is shared and unchanged,
only its remaining callers moved.  The movie/series equivalents live in
``tests/test_tmdb_discover_seeding.py``.  The adapter offset tests for
``get_top_movies``/``get_top_series`` stay: those methods still exist as
documented clients of ``/movie/popular`` and ``/tv/popular``.
"""

from unittest.mock import ANY, AsyncMock, MagicMock, patch

from sqlalchemy import func, select

from backlogg.books.adapters import open_library as ol_adapter
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.models import Movie
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import (
    SeedTargetRow,
    get_sync_offset,
    set_sync_offset,
    upsert_seed_targets,
)
from backlogg.series.adapters.tmdb import TMDBSeriesClient

# ── Cursor repository (real test DB) ─────────────────────────────────────────


async def test_get_sync_offset_returns_zero_when_absent(db):
    """An item_type without a persisted cursor starts at offset 0."""
    assert await get_sync_offset(db, "BOOK") == 0


async def test_set_and_get_sync_offset(db):
    """set_sync_offset persists a cursor that get_sync_offset reads back."""
    await set_sync_offset(db, "MOVIE", 200)
    assert await get_sync_offset(db, "MOVIE") == 200


async def test_set_sync_offset_upserts_existing_row(db):
    """Setting the cursor twice updates the single row (no duplicate PK)."""
    await set_sync_offset(db, "GAME", 100)
    await set_sync_offset(db, "GAME", 300)
    assert await get_sync_offset(db, "GAME") == 300


async def test_sync_cursors_are_independent_per_type(db):
    """Each item_type keeps its own cursor."""
    await set_sync_offset(db, "SERIES", 40)
    await set_sync_offset(db, "GAME", 80)
    assert await get_sync_offset(db, "SERIES") == 40
    assert await get_sync_offset(db, "GAME") == 80


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


async def test_open_library_passes_native_offset(monkeypatch):
    """Open Library popular search receives the offset as a native query param.

    Since feature 73 the global offset is split across the two filtered seed
    streams, so what travels on the wire is the stream's own sub-offset: with
    one spanish slot every 10, global slots 120..124 are all english and map
    to english sub-offset 120 - 12 = 108. The spanish stream contributes no
    slot to this slice, so a single request is issued.
    """
    monkeypatch.setattr(ol_adapter.settings, "BOOKS_SEED_ES_EVERY_N", 10)
    client = OpenLibraryClient()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "numFound": 16959,
        "docs": [{"key": f"/works/OL{i}W"} for i in range(5)],
    }
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=response,
    ) as mock_get:
        results = await client.get_popular_books(limit=5, offset=120)

    mock_get.assert_awaited_once()
    params = mock_get.call_args.kwargs["params"]
    assert params["limit"] == 5
    assert params["offset"] == 108
    assert params["q"] == ol_adapter.build_seed_query()
    assert params["sort"] == "readinglog"
    assert len(results) == 5


async def test_igdb_query_includes_offset_clause():
    """IGDB receives a native ``offset N;`` clause in the query body."""
    client = IGDBClient()
    with patch.object(client, "_post", new_callable=AsyncMock, return_value=[]) as mock_post:
        await client.get_top_games(limit=50, offset=200)

    mock_post.assert_awaited_once()
    body = mock_post.call_args.args[1]
    assert " limit 50;" in body
    assert " offset 200;" in body


# ── Job slice logic (adapters + cursor repo mocked) ───────────────────────────


def _mocked_session_factory():
    """Return a mock session factory whose context manager yields a mock session."""
    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_cm)


def _job_patches(cursor_offset: int):
    """Common patches for job slice tests: no network, no DB, cursor mocked."""
    return (
        patch(
            "backlogg.scheduler.jobs.get_sync_offset",
            new_callable=AsyncMock,
            return_value=cursor_offset,
        ),
        patch("backlogg.scheduler.jobs.set_sync_offset", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs._refresh_catalog_search", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory()),
    )


async def test_intermediate_slice_advances_cursor(monkeypatch):
    """A full intermediate slice advances the cursor by the fetched count."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_GAMES", 10)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 3)
    get_cursor, set_cursor, refresh, factory = _job_patches(cursor_offset=3)

    # Items without an external id are skipped by the upsert loop but still
    # count as fetched for cursor advancement.
    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_top_games",
            new_callable=AsyncMock,
            return_value=[{"id": None}] * 3,
        ) as mock_fetch,
        get_cursor,
        set_cursor as mock_set,
        refresh,
        factory,
    ):
        result = await sync_jobs.sync_games()

    mock_fetch.assert_awaited_once_with(limit=3, offset=3)
    mock_set.assert_awaited_once_with(ANY, "GAME", 6)
    assert result["offset"] == 3
    assert result["errors"] == 0


async def test_final_slice_wraps_to_zero(monkeypatch):
    """Reaching SEED_TOP_N_GAMES wraps the cursor back to 0."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_GAMES", 10)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 3)
    get_cursor, set_cursor, refresh, factory = _job_patches(cursor_offset=8)

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_top_games",
            new_callable=AsyncMock,
            return_value=[{"id": None}] * 2,
        ) as mock_fetch,
        get_cursor,
        set_cursor as mock_set,
        refresh,
        factory,
    ):
        result = await sync_jobs.sync_games()

    # Only target - offset = 2 items are requested for the final slice
    mock_fetch.assert_awaited_once_with(limit=2, offset=8)
    mock_set.assert_awaited_once_with(ANY, "GAME", 0)
    assert result["offset"] == 8


async def test_short_fetch_wraps_to_zero(monkeypatch):
    """The API returning fewer items than requested wraps the cursor to 0."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_GAMES", 10)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 3)
    get_cursor, set_cursor, refresh, factory = _job_patches(cursor_offset=3)

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_top_games",
            new_callable=AsyncMock,
            return_value=[{"id": None}],  # 1 < slice of 3 → catalog exhausted
        ) as mock_fetch,
        get_cursor,
        set_cursor as mock_set,
        refresh,
        factory,
    ):
        result = await sync_jobs.sync_games()

    mock_fetch.assert_awaited_once_with(limit=3, offset=3)
    mock_set.assert_awaited_once_with(ANY, "GAME", 0)
    assert result["offset"] == 3


async def test_stale_cursor_normalises_to_zero(monkeypatch):
    """A cursor at or beyond the target (e.g. after lowering SEED_TOP_N) restarts at 0."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_GAMES", 10)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 3)
    get_cursor, set_cursor, refresh, factory = _job_patches(cursor_offset=25)

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_top_games",
            new_callable=AsyncMock,
            return_value=[{"id": None}] * 3,
        ) as mock_fetch,
        get_cursor,
        set_cursor as mock_set,
        refresh,
        factory,
    ):
        result = await sync_jobs.sync_games()

    mock_fetch.assert_awaited_once_with(limit=3, offset=0)
    mock_set.assert_awaited_once_with(ANY, "GAME", 3)
    assert result["offset"] == 0


async def test_sync_books_slice_uses_cursor(monkeypatch):
    """sync_books fetches from its cursor and wraps on a short response."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_BOOKS", 20)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 5)
    get_cursor, set_cursor, refresh, factory = _job_patches(cursor_offset=10)

    with (
        patch.object(
            sync_jobs._ol_client,
            "get_popular_books",
            new_callable=AsyncMock,
            return_value=[{"key": "", "title": ""}] * 2,  # skipped: no title
        ) as mock_fetch,
        patch.object(sync_jobs._ol_client, "book_to_dict", return_value={"title": ""}),
        get_cursor,
        set_cursor as mock_set,
        refresh,
        factory,
    ):
        result = await sync_jobs.sync_books()

    mock_fetch.assert_awaited_once_with(limit=5, offset=10)
    mock_set.assert_awaited_once_with(ANY, "BOOK", 0)  # 2 < 5 → wraparound
    assert result["offset"] == 10


async def test_sync_games_slice_uses_cursor(monkeypatch):
    """sync_games fetches from its cursor and advances it."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_GAMES", 20)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 5)
    get_cursor, set_cursor, refresh, factory = _job_patches(cursor_offset=5)

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_top_games",
            new_callable=AsyncMock,
            return_value=[{"id": None}] * 5,
        ) as mock_fetch,
        get_cursor,
        set_cursor as mock_set,
        refresh,
        factory,
    ):
        result = await sync_jobs.sync_games()

    mock_fetch.assert_awaited_once_with(limit=5, offset=5)
    mock_set.assert_awaited_once_with(ANY, "GAME", 10)
    assert result["offset"] == 5


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
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
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
