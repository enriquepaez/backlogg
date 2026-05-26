"""Scheduler jobs — nightly sync for each content type.

Each job is an independent async coroutine.  Errors are logged but never
propagated so that a failure in one job does not abort the others.

After a successful upsert batch every job refreshes the catalog_search
materialized view so search results stay current.

Each job returns a dict with ``synced``, ``errors`` and ``duration_s`` so the
admin endpoint can expose the result synchronously.
"""

import logging
import time

from sqlalchemy import text

from backlogg.books import repository as books_repo
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.core.database import async_session_factory
from backlogg.games import repository as games_repo
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.movies import repository as movies_repo
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.series import repository as series_repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.shared.external_ids import upsert_external_id

logger = logging.getLogger(__name__)

_tmdb_movies = TMDBClient()
_tmdb_series = TMDBSeriesClient()
_ol_client = OpenLibraryClient()
_igdb_client = IGDBClient()


async def _refresh_catalog_search(session) -> None:
    """Refresh the catalog_search materialized view concurrently."""
    await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search"))
    await session.commit()


async def sync_movies() -> dict:
    """Fetch top popular movies from TMDB and upsert them into the local DB.

    Returns a dict with keys ``synced``, ``errors`` and ``duration_s``.
    """
    logger.info("sync_movies: starting")
    start = time.monotonic()
    synced = 0
    errors = 0

    try:
        raw_list = await _tmdb_movies.get_top_movies(limit=100)
    except Exception:
        logger.exception("sync_movies: failed to fetch from TMDB")
        return {"synced": 0, "errors": 1, "duration_s": round(time.monotonic() - start, 1)}

    async with async_session_factory() as session:
        for raw in raw_list:
            try:
                tmdb_id = raw.get("id")
                if not tmdb_id:
                    continue

                detail = await _tmdb_movies.get_movie_detail(tmdb_id)
                if detail is None:
                    continue

                movie_data = _tmdb_movies.movie_to_dict(detail)
                movie = await movies_repo.upsert_movie(session, movie_data)
                await upsert_external_id(session, "MOVIE", movie.id, "TMDB", str(tmdb_id))
                await session.flush()
                synced += 1
            except Exception:
                logger.exception("sync_movies: error upserting tmdb_id=%s", raw.get("id"))
                errors += 1

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_movies: failed to refresh catalog_search")

    logger.info("sync_movies: done — %d items upserted, %d errors", synced, errors)
    return {"synced": synced, "errors": errors, "duration_s": round(time.monotonic() - start, 1)}


async def sync_series() -> dict:
    """Fetch popular TV series from TMDB and upsert them into the local DB.

    Returns a dict with keys ``synced``, ``errors`` and ``duration_s``.
    """
    logger.info("sync_series: starting")
    start = time.monotonic()
    synced = 0
    errors = 0

    try:
        raw_list = await _tmdb_series.get_top_series(limit=100)
    except Exception:
        logger.exception("sync_series: failed to fetch from TMDB")
        return {"synced": 0, "errors": 1, "duration_s": round(time.monotonic() - start, 1)}

    async with async_session_factory() as session:
        for raw in raw_list:
            try:
                tmdb_id = raw.get("id")
                if not tmdb_id:
                    continue

                detail = await _tmdb_series.get_series_detail(tmdb_id)
                if detail is None:
                    continue

                series_data = _tmdb_series.series_to_dict(detail)
                series = await series_repo.upsert_series(session, series_data)
                await upsert_external_id(session, "SERIES", series.id, "TMDB", str(tmdb_id))
                await session.flush()
                synced += 1
            except Exception:
                logger.exception("sync_series: error upserting tmdb_id=%s", raw.get("id"))
                errors += 1

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_series: failed to refresh catalog_search")

    logger.info("sync_series: done — %d items upserted, %d errors", synced, errors)
    return {"synced": synced, "errors": errors, "duration_s": round(time.monotonic() - start, 1)}


async def sync_books() -> dict:
    """Fetch trending books from Open Library and upsert them into the local DB.

    Returns a dict with keys ``synced``, ``errors`` and ``duration_s``.
    """
    logger.info("sync_books: starting")
    start = time.monotonic()
    synced = 0
    errors = 0

    try:
        raw_list = await _ol_client.get_trending_books(limit=100)
    except Exception:
        logger.exception("sync_books: failed to fetch from Open Library")
        return {"synced": 0, "errors": 1, "duration_s": round(time.monotonic() - start, 1)}

    logger.error("sync_books: get_trending_books returned %d works", len(raw_list))

    async with async_session_factory() as session:
        for raw in raw_list:
            try:
                work_key = raw.get("key", "")
                work_id = work_key.removeprefix("/works/") if work_key else None

                # Normalize — trending endpoint returns a compact format; use
                # it as both the search doc and fetch full detail when possible.
                work_detail: dict | None = None
                if work_id:
                    work_detail = await _ol_client.get_work_detail(work_id)

                # Build a pseudo search_doc from the trending entry
                search_doc: dict = {
                    "title": raw.get("title", ""),
                    "key": work_key,
                    "first_publish_year": raw.get("first_publish_year"),
                    "cover_i": raw.get("cover_i") or raw.get("cover_id"),
                    "subject": raw.get("subject", []),
                    "author_name": raw.get("author_name", []),
                }

                book_data = _ol_client.book_to_dict(search_doc, work_detail)
                if not book_data.get("title"):
                    continue

                book = await books_repo.upsert_book(session, book_data)
                if work_id:
                    await upsert_external_id(session, "BOOK", book.id, "OPEN_LIBRARY", work_id)
                await session.flush()
                synced += 1
            except Exception:
                logger.exception("sync_books: error upserting work_key=%s", raw.get("key"))
                errors += 1

        logger.error(
            "sync_books: loop done — synced=%d errors=%d out_of=%d",
            synced,
            errors,
            len(raw_list),
        )

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_books: failed to refresh catalog_search")

    logger.info("sync_books: done — %d items upserted, %d errors", synced, errors)
    return {"synced": synced, "errors": errors, "duration_s": round(time.monotonic() - start, 1)}


async def sync_games() -> dict:
    """Fetch top-rated games from IGDB and upsert them into the local DB.

    Returns a dict with keys ``synced``, ``errors`` and ``duration_s``.
    """
    logger.info("sync_games: starting")
    start = time.monotonic()
    synced = 0
    errors = 0

    try:
        raw_list = await _igdb_client.get_top_games(limit=100)
    except Exception:
        logger.exception("sync_games: failed to fetch from IGDB")
        return {"synced": 0, "errors": 1, "duration_s": round(time.monotonic() - start, 1)}

    async with async_session_factory() as session:
        for raw in raw_list:
            try:
                igdb_id = raw.get("id")
                if not igdb_id:
                    continue

                game_data = _igdb_client.game_to_dict(raw)
                game = await games_repo.upsert_game(session, game_data)
                await upsert_external_id(session, "GAME", game.id, "IGDB", str(igdb_id))
                await session.flush()
                synced += 1
            except Exception:
                logger.exception("sync_games: error upserting igdb_id=%s", raw.get("id"))
                errors += 1

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_games: failed to refresh catalog_search")

    logger.info("sync_games: done — %d items upserted, %d errors", synced, errors)
    return {"synced": synced, "errors": errors, "duration_s": round(time.monotonic() - start, 1)}
