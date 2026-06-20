"""Search service with on-demand external fallback.

When a query returns 0 local results the service fans out in parallel to the
external APIs (TMDB movies, TMDB series, Open Library books, IGDB games),
ingests the top hits, refreshes the catalog_search materialized view and
re-executes the local search query before returning.

If ``item_type`` is set only the corresponding API is consulted.

Failures in individual external APIs are caught and logged — they never
abort the other fan-out tasks or return an error to the caller.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books import repository as books_repo
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.core.database import async_session_factory
from backlogg.games import repository as games_repo
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.movies import repository as movies_repo
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.search.repository import SearchRepository
from backlogg.series import repository as series_repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.shared.external_ids import upsert_external_id

logger = logging.getLogger(__name__)

# Module-level singletons — each client is lightweight and stateless except
# for the IGDB token cache which is safe to share across requests.
_tmdb_movies = TMDBClient()
_tmdb_series = TMDBSeriesClient()
_ol_client = OpenLibraryClient()
_igdb_client = IGDBClient()

# How many top hits to ingest per external source during a search fallback
_FANOUT_LIMIT = 5


async def _ingest_movies(q: str) -> None:
    """Search TMDB for movies matching *q* and persist the top hits."""
    try:
        raw = await _tmdb_movies.search_movie(q)
        if raw is None:
            return
        tmdb_id = raw.get("id")
        if not tmdb_id:
            return
        detail = await _tmdb_movies.get_movie_detail(tmdb_id)
        if detail is None:
            return
        movie_data = _tmdb_movies.movie_to_dict(detail)
        async with async_session_factory() as db:
            async with db.begin():
                movie = await movies_repo.upsert_movie(db, movie_data)
                await upsert_external_id(db, "MOVIE", movie.id, "TMDB", str(tmdb_id))
    except Exception:
        logger.exception("search fallback: error ingesting movies for q=%r", q)


async def _ingest_series(q: str) -> None:
    """Search TMDB for series matching *q* and persist the top hits."""
    try:
        raw = await _tmdb_series.search_series(q)
        if raw is None:
            return
        tmdb_id = raw.get("id")
        if not tmdb_id:
            return
        detail = await _tmdb_series.get_series_detail(tmdb_id)
        if detail is None:
            return
        series_data = _tmdb_series.series_to_dict(detail)
        async with async_session_factory() as db:
            async with db.begin():
                series = await series_repo.upsert_series(db, series_data)
                await upsert_external_id(db, "SERIES", series.id, "TMDB", str(tmdb_id))
    except Exception:
        logger.exception("search fallback: error ingesting series for q=%r", q)


async def _ingest_books(q: str) -> None:
    """Search Open Library for books matching *q* and persist the top hits."""
    try:
        raw = await _ol_client.search_book(q)
        if raw is None:
            return
        work_key = raw.get("key", "")
        work_id = work_key.removeprefix("/works/") if work_key else None
        work_detail: dict | None = None
        if work_id:
            work_detail = await _ol_client.get_work_detail(work_id)
        book_data = _ol_client.book_to_dict(raw, work_detail)
        if not book_data.get("title"):
            return
        async with async_session_factory() as db:
            async with db.begin():
                book = await books_repo.upsert_book(db, book_data)
                if work_id:
                    await upsert_external_id(db, "BOOK", book.id, "OPEN_LIBRARY", work_id)
    except Exception:
        logger.exception("search fallback: error ingesting books for q=%r", q)


async def _ingest_games(q: str) -> None:
    """Search IGDB for games matching *q* and persist the top hits."""
    try:
        results = await _igdb_client.search_games(q, limit=_FANOUT_LIMIT)
        async with async_session_factory() as db:
            async with db.begin():
                for raw in results:
                    try:
                        igdb_id = raw.get("id")
                        if not igdb_id:
                            continue
                        game_data = _igdb_client.game_to_dict(raw)
                        async with db.begin_nested():  # savepoint per game
                            game = await games_repo.upsert_game(db, game_data)
                            await upsert_external_id(db, "GAME", game.id, "IGDB", str(igdb_id))
                    except Exception:
                        logger.exception(
                            "search fallback: error ingesting game igdb_id=%s for q=%r",
                            raw.get("id"),
                            q,
                        )
    except Exception:
        logger.exception("search fallback: error searching IGDB for q=%r", q)


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = SearchRepository(session)

    async def search(
        self,
        q: str,
        item_type: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        """Search the catalog and return (results, total).

        If the local catalog returns 0 results, fan-out to external APIs,
        ingest the hits, refresh the materialized view and re-query.
        """
        results, total = await self._repo.search(q=q, item_type=item_type, page=page, limit=limit)

        if total > 0:
            # Fast path — local results found, skip fan-out
            return results, total

        # Slow path — fan-out to external APIs in parallel
        tasks = []
        if item_type is None or item_type == "movie":
            tasks.append(_ingest_movies(q))
        if item_type is None or item_type == "series":
            tasks.append(_ingest_series(q))
        if item_type is None or item_type == "book":
            tasks.append(_ingest_books(q))
        if item_type is None or item_type == "game":
            tasks.append(_ingest_games(q))

        # gather with return_exceptions=True so one failure never aborts others
        await asyncio.gather(*tasks, return_exceptions=True)

        # Refresh the materialized view so the newly inserted rows are searchable
        await self._repo.refresh_catalog_search()

        # Re-query the local catalog with the freshly ingested data
        results, total = await self._repo.search(q=q, item_type=item_type, page=page, limit=limit)
        return results, total
