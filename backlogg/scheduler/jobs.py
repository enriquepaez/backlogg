"""Scheduler jobs — nightly sync for each content type.

Each job is an independent async coroutine.  Errors are logged but never
propagated so that a failure in one job does not abort the others.

Every run processes a slice of the external API's popular listing: it reads
the persisted cursor for its type from ``sync_cursors`` (0 if absent),
fetches up to ``settings.SYNC_SLICE_SIZE`` items starting at that offset
(never beyond ``settings.SEED_TOP_N_<TYPE>``) and advances the cursor at the
end.  The cursor wraps around to 0 when the target is reached or when the
API returns fewer items than requested.

After a successful upsert batch every job refreshes the catalog_search
materialized view so search results stay current.

Each job returns a dict with ``synced``, ``errors``, ``offset`` (the offset
of the processed slice) and ``duration_s`` so the admin endpoint can expose
the result synchronously.
"""

import logging
import time

from sqlalchemy import text

from backlogg.books import repository as books_repo
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.books.service import _persist_book_authors
from backlogg.core.config import settings
from backlogg.core.database import async_session_factory
from backlogg.games import repository as games_repo
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.movies import repository as movies_repo
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.service import _persist_movie_people
from backlogg.scheduler.repository import get_sync_offset, set_sync_offset
from backlogg.series import repository as series_repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.series.service import _persist_series_creators, _persist_series_people
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


async def _read_slice(item_type: str, target: int) -> tuple[int, int]:
    """Return (offset, slice_size) for the next sync slice of ``item_type``.

    Reads the persisted cursor (0 if absent).  A stale cursor at or beyond
    ``target`` (e.g. after lowering SEED_TOP_N) is normalised back to 0.
    """
    async with async_session_factory() as session:
        offset = await get_sync_offset(session, item_type)
    if offset >= target:
        offset = 0
    return offset, min(settings.SYNC_SLICE_SIZE, target - offset)


def _next_offset(offset: int, fetched: int, slice_size: int, target: int) -> int:
    """Advance the cursor, wrapping to 0 at ``target`` or on a short fetch."""
    advanced = offset + fetched
    if fetched < slice_size or advanced >= target:
        return 0
    return advanced


async def _persist_cursor(session, item_type: str, next_offset: int, job_name: str) -> None:
    """Persist the cursor in the job's session; failures are logged, not raised."""
    try:
        await set_sync_offset(session, item_type, next_offset)
        await session.commit()
    except Exception:
        logger.exception("%s: failed to persist sync cursor", job_name)


async def sync_movies() -> dict:
    """Fetch a slice of top popular movies from TMDB and upsert them locally.

    Returns a dict with keys ``synced``, ``errors``, ``offset`` and ``duration_s``.
    """
    logger.info("sync_movies: starting")
    start = time.monotonic()
    synced = 0
    errors = 0
    target = settings.SEED_TOP_N_MOVIES

    try:
        offset, slice_size = await _read_slice("MOVIE", target)
    except Exception:
        logger.exception("sync_movies: failed to read sync cursor")
        return {
            "synced": 0,
            "errors": 1,
            "offset": 0,
            "duration_s": round(time.monotonic() - start, 1),
        }

    try:
        raw_list = await _tmdb_movies.get_top_movies(limit=slice_size, offset=offset)
    except Exception:
        logger.exception("sync_movies: failed to fetch from TMDB")
        return {
            "synced": 0,
            "errors": 1,
            "offset": offset,
            "duration_s": round(time.monotonic() - start, 1),
        }

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

                try:
                    await _persist_movie_people(session, movie, tmdb_id)
                except Exception:
                    logger.exception(
                        "sync_movies: failed to persist people for tmdb_id=%s", tmdb_id
                    )
            except Exception:
                logger.exception("sync_movies: error upserting tmdb_id=%s", raw.get("id"))
                errors += 1

        await _persist_cursor(
            session, "MOVIE", _next_offset(offset, len(raw_list), slice_size, target), "sync_movies"
        )

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_movies: failed to refresh catalog_search")

    logger.info(
        "sync_movies: done — %d items upserted, %d errors (offset %d)", synced, errors, offset
    )
    return {
        "synced": synced,
        "errors": errors,
        "offset": offset,
        "duration_s": round(time.monotonic() - start, 1),
    }


async def sync_series() -> dict:
    """Fetch a slice of popular TV series from TMDB and upsert them locally.

    Returns a dict with keys ``synced``, ``errors``, ``offset`` and ``duration_s``.
    """
    logger.info("sync_series: starting")
    start = time.monotonic()
    synced = 0
    errors = 0
    target = settings.SEED_TOP_N_SERIES

    try:
        offset, slice_size = await _read_slice("SERIES", target)
    except Exception:
        logger.exception("sync_series: failed to read sync cursor")
        return {
            "synced": 0,
            "errors": 1,
            "offset": 0,
            "duration_s": round(time.monotonic() - start, 1),
        }

    try:
        raw_list = await _tmdb_series.get_top_series(limit=slice_size, offset=offset)
    except Exception:
        logger.exception("sync_series: failed to fetch from TMDB")
        return {
            "synced": 0,
            "errors": 1,
            "offset": offset,
            "duration_s": round(time.monotonic() - start, 1),
        }

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

                try:
                    await _persist_series_people(session, series, tmdb_id)
                    created_by = detail.get("created_by", [])
                    if created_by:
                        await _persist_series_creators(session, series, created_by)
                except Exception:
                    logger.exception(
                        "sync_series: failed to persist people for tmdb_id=%s", tmdb_id
                    )
            except Exception:
                logger.exception("sync_series: error upserting tmdb_id=%s", raw.get("id"))
                errors += 1

        await _persist_cursor(
            session,
            "SERIES",
            _next_offset(offset, len(raw_list), slice_size, target),
            "sync_series",
        )

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_series: failed to refresh catalog_search")

    logger.info(
        "sync_series: done — %d items upserted, %d errors (offset %d)", synced, errors, offset
    )
    return {
        "synced": synced,
        "errors": errors,
        "offset": offset,
        "duration_s": round(time.monotonic() - start, 1),
    }


async def sync_books() -> dict:
    """Fetch a slice of trending books from Open Library and upsert them locally.

    Returns a dict with keys ``synced``, ``errors``, ``offset`` and ``duration_s``.
    """
    logger.info("sync_books: starting")
    start = time.monotonic()
    synced = 0
    errors = 0
    target = settings.SEED_TOP_N_BOOKS

    try:
        offset, slice_size = await _read_slice("BOOK", target)
    except Exception:
        logger.exception("sync_books: failed to read sync cursor")
        return {
            "synced": 0,
            "errors": 1,
            "offset": 0,
            "duration_s": round(time.monotonic() - start, 1),
        }

    try:
        raw_list = await _ol_client.get_trending_books(limit=slice_size, offset=offset)
    except Exception:
        logger.exception("sync_books: failed to fetch from Open Library")
        return {
            "synced": 0,
            "errors": 1,
            "offset": offset,
            "duration_s": round(time.monotonic() - start, 1),
        }

    async with async_session_factory() as session:
        for raw in raw_list:
            try:
                work_key = raw.get("key", "")
                work_id = work_key.removeprefix("/works/") if work_key else None

                search_doc: dict = {
                    "title": raw.get("title", ""),
                    "key": work_key,
                    "first_publish_year": raw.get("first_publish_year"),
                    "cover_i": raw.get("cover_i") or raw.get("cover_id"),
                    "subject": raw.get("subject", []),
                    "author_name": raw.get("author_name", []),
                }

                book_data = _ol_client.book_to_dict(search_doc, None)
                if not book_data.get("title"):
                    continue

                book = await books_repo.upsert_book(session, book_data)
                if work_id:
                    await upsert_external_id(session, "BOOK", book.id, "OPEN_LIBRARY", work_id)
                await session.flush()
                synced += 1

                if work_id:
                    try:
                        work_detail = await _ol_client.get_work_detail(work_id)
                        if work_detail:
                            await _persist_book_authors(session, book, work_detail)
                    except Exception:
                        logger.exception(
                            "sync_books: failed to persist authors for work_id=%s", work_id
                        )
            except Exception:
                logger.exception("sync_books: error upserting work_key=%s", raw.get("key"))
                errors += 1

        await _persist_cursor(
            session, "BOOK", _next_offset(offset, len(raw_list), slice_size, target), "sync_books"
        )

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_books: failed to refresh catalog_search")

    logger.info(
        "sync_books: done — %d items upserted, %d errors (offset %d)", synced, errors, offset
    )
    return {
        "synced": synced,
        "errors": errors,
        "offset": offset,
        "duration_s": round(time.monotonic() - start, 1),
    }


async def sync_games() -> dict:
    """Fetch a slice of top-rated games from IGDB and upsert them locally.

    Returns a dict with keys ``synced``, ``errors``, ``offset`` and ``duration_s``.
    """
    logger.info("sync_games: starting")
    start = time.monotonic()
    synced = 0
    errors = 0
    target = settings.SEED_TOP_N_GAMES

    try:
        offset, slice_size = await _read_slice("GAME", target)
    except Exception:
        logger.exception("sync_games: failed to read sync cursor")
        return {
            "synced": 0,
            "errors": 1,
            "offset": 0,
            "duration_s": round(time.monotonic() - start, 1),
        }

    try:
        raw_list = await _igdb_client.get_top_games(limit=slice_size, offset=offset)
    except Exception:
        logger.exception("sync_games: failed to fetch from IGDB")
        return {
            "synced": 0,
            "errors": 1,
            "offset": offset,
            "duration_s": round(time.monotonic() - start, 1),
        }

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

        await _persist_cursor(
            session, "GAME", _next_offset(offset, len(raw_list), slice_size, target), "sync_games"
        )

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_games: failed to refresh catalog_search")

    logger.info(
        "sync_games: done — %d items upserted, %d errors (offset %d)", synced, errors, offset
    )
    return {
        "synced": synced,
        "errors": errors,
        "offset": offset,
        "duration_s": round(time.monotonic() - start, 1),
    }
