"""Search service with on-demand external fallback.

The fan-out to external APIs (TMDB movies, TMDB series, Open Library books,
IGDB games) fires in two situations:

* **Any page that comes back incomplete** (fewer local rows than ``limit`` —
  this includes, but is not limited to, 0 results). This lets the catalog
  fill in gradually as a user pages through a query whose local catalog is
  still incomplete.
* **Page 1 of any text query**, at least once every
  ``_FANOUT_QUERY_CACHE_TTL_SECONDS``, even when the local page is already
  fully populated. A broad, popular query (e.g. "final fantasy") can have
  more than enough local rows to fill page after page without any page ever
  coming back short, so the "incomplete page" trigger alone would never
  check the external APIs again once the first page filled up — silently
  missing well-known items (e.g. a single unsynced entry in a large
  franchise) that never surface because no page is ever incomplete. Repeat
  identical page-1 requests (same ``q``/``item_type``) within the TTL are
  deduplicated via ``core/cache`` so a popular term does not hammer
  TMDB/Open Library/IGDB on every request.

Each fan-out ingests up to ``limit`` hits from the externally-mapped page
(only as many as will actually be shown to the caller), refreshes the
catalog_search materialized view and re-executes the local search query
before returning.

The external page consulted is derived deterministically from the local
``page``/``limit`` — no fan-out cursor/state is persisted. As the caller
pages further into a query whose local catalog is still incomplete, the
fan-out keeps walking further external pages, growing the local catalog for
that query page by page.

If ``item_type`` is set only the corresponding API is consulted.

Failures in individual external APIs are caught and logged — they never
abort the other fan-out tasks or return an error to the caller.
"""

import asyncio
import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books import repository as books_repo
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.books.service import _persist_book_authors
from backlogg.core.cache import get_cache
from backlogg.core.database import async_session_factory
from backlogg.core.metrics import get_metrics
from backlogg.core.rate_limit import enforce_search_fallback
from backlogg.games import repository as games_repo
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.games.constants import ALLOWED_GAME_TYPES
from backlogg.movies import repository as movies_repo
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.service import _persist_movie_people
from backlogg.search.repository import SearchRepository
from backlogg.series import repository as series_repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.series.service import _persist_series_creators, _persist_series_people
from backlogg.shared.external_ids import upsert_external_id

logger = logging.getLogger(__name__)

# Module-level singletons — each client is lightweight and stateless except
# for the IGDB token cache which is safe to share across requests.
_tmdb_movies = TMDBClient()
_tmdb_series = TMDBSeriesClient()
_ol_client = OpenLibraryClient()
_igdb_client = IGDBClient()

# TMDB's fixed native page size (also used as the limit/per-page requested
# from Open Library and IGDB per fan-out call, so every source is walked in
# lockstep pages of this size).
_FANOUT_PAGE_SIZE = 20

# Max number of concurrent per-item detail-fetch HTTP calls (movies/series/
# books) within a single fan-out. The external search/list call itself still
# requests a full _FANOUT_PAGE_SIZE page (so _external_page() stays aligned),
# but only ``limit`` of those hits are ever detail-fetched/upserted — no
# point paying the network+DB cost for rows the caller will not see on this
# page. Bounded so a query with many hits does not fire a burst of
# concurrent requests at TMDB/Open Library.
_DETAIL_FETCH_CONCURRENCY = 5

# How long a page-1 "already checked the external APIs" marker stays valid
# for a given (item_type, q) pair. Bounds how often a popular, already
# fully-populated query re-triggers the fan-out — without this, an
# already-full page 1 would either never fan out again (stale gaps never
# fill in) or fan out on every single request (hammering TMDB/Open
# Library/IGDB for a hot term).
_FANOUT_QUERY_CACHE_TTL_SECONDS = 600


def _fanout_cache_key(q: str, item_type: str | None) -> str:
    """Cache key for the page-1 "already checked externally" marker.

    Scoped by ``item_type`` (a movie-only fan-out for a query does not mark
    the book/series/game fan-out for that same query as checked) and
    normalized (lowercased/stripped) so trivial casing/whitespace variants
    of the same query share the cache entry.
    """
    return f"search_fanout:{item_type or 'all'}:{q.strip().lower()}"


def _external_page(page: int, limit: int) -> int:
    """Map the local (1-based) ``page``/``limit`` to a 1-based external page.

    Deterministic, no persisted cursor: the local offset is translated into
    units of ``_FANOUT_PAGE_SIZE`` so that as the caller pages further into a
    query with an incomplete local catalog, the fan-out keeps walking further
    external pages.
    """
    offset = (page - 1) * limit
    return offset // _FANOUT_PAGE_SIZE + 1


async def _fetch_movie_detail(sem: asyncio.Semaphore, q: str, tmdb_id: int) -> dict | None:
    """Fetch one TMDB movie detail under *sem*, logging and swallowing errors."""
    async with sem:
        try:
            return await _tmdb_movies.get_movie_detail(tmdb_id)
        except Exception:
            logger.exception(
                "search fallback: error ingesting movie tmdb_id=%s for q=%r",
                tmdb_id,
                q,
            )
            return None


async def _ingest_movies(q: str, page: int, limit: int) -> None:
    """Search TMDB for movies matching *q* and persist up to *limit* hits from the mapped page."""
    get_metrics().inc_counter("backlogg_external_fanout_total", labels={"source": "movie"})
    external_page = _external_page(page, limit)
    try:
        results = await _tmdb_movies.search_movie(q, page=external_page)
        # Only detail-fetch/persist as many hits as the caller will actually
        # see on this page — the search call above still requested a full
        # _FANOUT_PAGE_SIZE page so _external_page() stays aligned.
        candidates = [raw.get("id") for raw in results[:limit] if raw.get("id")]

        # Fetch phase — network calls in parallel, bounded by a semaphore.
        sem = asyncio.Semaphore(_DETAIL_FETCH_CONCURRENCY)
        details = await asyncio.gather(
            *(_fetch_movie_detail(sem, q, tmdb_id) for tmdb_id in candidates),
            return_exceptions=True,
        )

        # Persist phase — sequential, AsyncSession is not safe for concurrent writes.
        async with async_session_factory() as db:
            async with db.begin():
                for tmdb_id, outcome in zip(candidates, details, strict=True):
                    if isinstance(outcome, BaseException):
                        logger.exception(
                            "search fallback: error ingesting movie tmdb_id=%s for q=%r",
                            tmdb_id,
                            q,
                            exc_info=outcome,
                        )
                        continue
                    detail = outcome
                    if detail is None:
                        continue
                    try:
                        movie_data = _tmdb_movies.movie_to_dict(detail)
                        async with db.begin_nested():  # savepoint per movie
                            # Row-just-created check (same pattern as the
                            # on-demand/similar/trending paths) so credits are
                            # only fetched once per movie, not on every
                            # re-ingestion of an already-persisted slug.
                            is_new = (
                                await movies_repo.get_movie_by_slug(db, movie_data["slug"]) is None
                            )
                            movie = await movies_repo.upsert_movie(db, movie_data)
                            await upsert_external_id(db, "MOVIE", movie.id, "TMDB", str(tmdb_id))
                            if is_new:
                                # Persist people (cast + directors) — feature
                                # 70: this fallback path previously left
                                # movies without credits forever.
                                await _persist_movie_people(db, movie, tmdb_id)
                    except Exception:
                        logger.exception(
                            "search fallback: error ingesting movie tmdb_id=%s for q=%r",
                            tmdb_id,
                            q,
                        )
    except Exception:
        logger.exception("search fallback: error searching TMDB movies for q=%r", q)


async def _fetch_series_detail(sem: asyncio.Semaphore, q: str, tmdb_id: int) -> dict | None:
    """Fetch one TMDB series detail under *sem*, logging and swallowing errors."""
    async with sem:
        try:
            return await _tmdb_series.get_series_detail(tmdb_id)
        except Exception:
            logger.exception(
                "search fallback: error ingesting series tmdb_id=%s for q=%r",
                tmdb_id,
                q,
            )
            return None


async def _ingest_series(q: str, page: int, limit: int) -> None:
    """Search TMDB for series matching *q* and persist up to *limit* hits from the mapped page."""
    get_metrics().inc_counter("backlogg_external_fanout_total", labels={"source": "series"})
    external_page = _external_page(page, limit)
    try:
        results = await _tmdb_series.search_series(q, page=external_page)
        candidates = [raw.get("id") for raw in results[:limit] if raw.get("id")]

        sem = asyncio.Semaphore(_DETAIL_FETCH_CONCURRENCY)
        details = await asyncio.gather(
            *(_fetch_series_detail(sem, q, tmdb_id) for tmdb_id in candidates),
            return_exceptions=True,
        )

        async with async_session_factory() as db:
            async with db.begin():
                for tmdb_id, outcome in zip(candidates, details, strict=True):
                    if isinstance(outcome, BaseException):
                        logger.exception(
                            "search fallback: error ingesting series tmdb_id=%s for q=%r",
                            tmdb_id,
                            q,
                            exc_info=outcome,
                        )
                        continue
                    detail = outcome
                    if detail is None:
                        continue
                    try:
                        series_data = _tmdb_series.series_to_dict(detail)
                        async with db.begin_nested():  # savepoint per series
                            # Row-just-created check (same pattern as the
                            # on-demand/similar/trending paths) so credits
                            # are only fetched once per series.
                            is_new = (
                                await series_repo.get_series_by_slug(db, series_data["slug"])
                                is None
                            )
                            series = await series_repo.upsert_series(db, series_data)
                            await upsert_external_id(db, "SERIES", series.id, "TMDB", str(tmdb_id))
                            if is_new:
                                # Persist people (cast + creators) — feature
                                # 70: this fallback path previously left
                                # series without credits forever.
                                await _persist_series_people(db, series, tmdb_id)
                                created_by = detail.get("created_by", [])
                                if created_by:
                                    await _persist_series_creators(db, series, created_by)
                    except Exception:
                        logger.exception(
                            "search fallback: error ingesting series tmdb_id=%s for q=%r",
                            tmdb_id,
                            q,
                        )
    except Exception:
        logger.exception("search fallback: error searching TMDB series for q=%r", q)


async def _fetch_book_detail(
    sem: asyncio.Semaphore, q: str, raw: dict
) -> tuple[str | None, dict | None]:
    """Fetch one Open Library work detail under *sem*, logging and swallowing errors.

    Returns ``(work_id, work_detail)`` — ``work_id`` is ``None`` (and no
    network call is made) when *raw* has no ``key``, mirroring the original
    behaviour.
    """
    work_key = raw.get("key", "")
    work_id = work_key.removeprefix("/works/") if work_key else None
    if not work_id:
        return None, None
    async with sem:
        try:
            return work_id, await _ol_client.get_work_detail(work_id)
        except Exception:
            logger.exception(
                "search fallback: error ingesting book key=%r for q=%r",
                raw.get("key"),
                q,
            )
            return work_id, None


async def _ingest_books(q: str, page: int, limit: int) -> None:
    """Search Open Library for *q*; persist up to *limit* hits from the mapped page."""
    get_metrics().inc_counter("backlogg_external_fanout_total", labels={"source": "book"})
    external_page = _external_page(page, limit)
    try:
        results = await _ol_client.search_book(q, page=external_page, limit=_FANOUT_PAGE_SIZE)
        candidates = results[:limit]

        sem = asyncio.Semaphore(_DETAIL_FETCH_CONCURRENCY)
        fetched = await asyncio.gather(
            *(_fetch_book_detail(sem, q, raw) for raw in candidates),
            return_exceptions=True,
        )

        async with async_session_factory() as db:
            async with db.begin():
                for raw, outcome in zip(candidates, fetched, strict=True):
                    if isinstance(outcome, BaseException):
                        logger.exception(
                            "search fallback: error ingesting book key=%r for q=%r",
                            raw.get("key"),
                            q,
                            exc_info=outcome,
                        )
                        continue
                    work_id, work_detail = outcome
                    try:
                        book_data = _ol_client.book_to_dict(raw, work_detail)
                        if not book_data.get("title"):
                            continue
                        async with db.begin_nested():  # savepoint per book
                            # Row-just-created check (same pattern as the
                            # on-demand path) so authors are only fetched
                            # once per book.
                            is_new = (
                                await books_repo.get_book_by_slug(db, book_data["slug"]) is None
                            )
                            book = await books_repo.upsert_book(db, book_data)
                            if work_id:
                                await upsert_external_id(
                                    db, "BOOK", book.id, "OPEN_LIBRARY", work_id
                                )
                            if is_new and work_detail:
                                # Persist authors — feature 70: this
                                # fallback path previously left books
                                # without authorship credits forever.
                                await _persist_book_authors(db, book, work_detail)
                    except Exception:
                        logger.exception(
                            "search fallback: error ingesting book key=%r for q=%r",
                            raw.get("key"),
                            q,
                        )
    except Exception:
        logger.exception("search fallback: error searching Open Library for q=%r", q)


async def _ingest_games(q: str, page: int, limit: int) -> None:
    """Search IGDB for games matching *q* and persist up to *limit* hits from the mapped page."""
    get_metrics().inc_counter("backlogg_external_fanout_total", labels={"source": "game"})
    external_page = _external_page(page, limit)
    offset = (external_page - 1) * _FANOUT_PAGE_SIZE
    try:
        results = await _igdb_client.search_games(q, limit=_FANOUT_PAGE_SIZE, offset=offset)
        # IGDB returns full item data in the bulk search response (no
        # per-item detail call) — only the upsert loop needs capping.
        results = results[:limit]
        async with async_session_factory() as db:
            async with db.begin():
                for raw in results:
                    try:
                        igdb_id = raw.get("id")
                        if not igdb_id:
                            continue
                        game_data = _igdb_client.game_to_dict(raw)
                        if game_data["game_type"] not in ALLOWED_GAME_TYPES:
                            # Disallowed category (feature 65) — never ingested.
                            continue
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
        q: str | None,
        item_type: str | None = None,
        page: int = 1,
        limit: int = 20,
        client_ip: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        rating_external_min: float | None = None,
        rating_external_max: float | None = None,
    ) -> tuple[list[dict], int]:
        """Search the catalog and return (results, total).

        When ``q`` is ``None`` this is a pure filter query (date/rating range
        only) — the external fan-out never fires, since external APIs need a
        text term to search against, not date/rating filters.

        When ``q`` is provided, the external fan-out fires when either is true:

        * The requested page comes back with fewer than ``limit`` local
          results — this covers 0 results, but also any other
          partially-populated page, including page 1.
        * It is page 1 and this exact ``q``/``item_type`` pair has not been
          fanned out for within the last ``_FANOUT_QUERY_CACHE_TTL_SECONDS``
          (tracked via ``core.cache``). This guarantees page 1 of any text
          search checks the external APIs at least once per TTL window even
          when the local catalog already has more than enough rows to fill
          that page — otherwise a broad, popular query would never trigger a
          page-1 fan-out again once it first filled up, silently missing
          items that never make any page come back short. Pages beyond 1 are
          unaffected by this cache — they keep firing solely based on
          whether the page came back incomplete, unchanged from before.

        Each fan-out ingests up to ``limit`` hits from the externally-mapped
        page, refreshes the materialized view and re-queries.

        The external fan-out is rate limited per ``client_ip`` (when provided)
        so a burst of misses cannot hammer the external APIs. Queries whose
        page is already fully populated from the local catalog and were
        already checked within the TTL do not consume any quota.
        """
        results, total = await self._repo.search(
            q=q,
            item_type=item_type,
            page=page,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
            rating_external_min=rating_external_min,
            rating_external_max=rating_external_max,
        )

        page_incomplete = len(results) < limit
        cache = get_cache()
        fanout_cache_key = _fanout_cache_key(q, item_type) if q is not None else None
        already_checked_recently = (
            fanout_cache_key is not None and cache.get(fanout_cache_key) is not None
        )
        should_fanout = q is not None and (
            page_incomplete or (page == 1 and not already_checked_recently)
        )

        if not should_fanout:
            # Fast path — there is no text term to fan out with (external
            # APIs cannot be searched by date/rating filters alone), or the
            # local page is already full and (for page 1) was already
            # checked externally within the TTL.
            return results, total

        # Gate the external fan-out per IP before touching any external API.
        if client_ip is not None:
            enforce_search_fallback(client_ip)

        if page == 1 and fanout_cache_key is not None:
            # Mark this query as checked before firing so a burst of
            # identical page-1 requests within the TTL only fans out once —
            # this only ever suppresses a page-1 fan-out for an
            # already-fully-populated page; an incomplete page always fans
            # out regardless of this marker.
            cache.set(fanout_cache_key, True, _FANOUT_QUERY_CACHE_TTL_SECONDS)

        # Slow path — fan-out to external APIs in parallel
        tasks = []
        if item_type is None or item_type == "movie":
            tasks.append(_ingest_movies(q, page, limit))
        if item_type is None or item_type == "series":
            tasks.append(_ingest_series(q, page, limit))
        if item_type is None or item_type == "book":
            tasks.append(_ingest_books(q, page, limit))
        if item_type is None or item_type == "game":
            tasks.append(_ingest_games(q, page, limit))

        # gather with return_exceptions=True so one failure never aborts others
        await asyncio.gather(*tasks, return_exceptions=True)

        # Refresh the materialized view so the newly inserted rows are searchable
        await self._repo.refresh_catalog_search()

        # Re-query the local catalog with the freshly ingested data
        results, total = await self._repo.search(
            q=q,
            item_type=item_type,
            page=page,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
            rating_external_min=rating_external_min,
            rating_external_max=rating_external_max,
        )
        return results, total
