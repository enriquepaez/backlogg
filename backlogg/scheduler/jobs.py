"""Scheduler jobs — nightly sync for each content type.

Each job is an independent async coroutine.  Errors are logged but never
propagated so that a failure in one job does not abort the others.

Every run processes a slice of the external API's popular listing: it reads
the persisted cursor for its type from ``sync_cursors`` (0 if absent),
fetches up to the type's slice size starting at that offset (never beyond
``settings.SEED_TOP_N_<TYPE>``) and advances the cursor at the end.  The
cursor wraps around to 0 when the target is reached or when the API returns
fewer items than requested.

Slice size is resolved per type (feature 84): an explicit ``slice_size``
argument wins (that is how ``scripts/backfill_sync.py`` processes bigger
slices), then ``settings.SYNC_SLICE_SIZE_<TYPE>``, then the global
``settings.SYNC_SLICE_SIZE``.  Movies and series genuinely need different
numbers — TMDB's 6-month cache window forces ~350 movies/night against ~61
series — so a single global knob could not serve both.

Write path (feature 84)
-----------------------

Items are *fetched* one by one (that part is the external API's shape) but
*written* in batches through ``backlogg.shared.bulk_load``: COPY into temp
tables plus ``INSERT ... SELECT ... ON CONFLICT``, with every person of the
batch resolved by a single query.  That turns the 35-75 SQL round trips per
item of the old route into a handful per batch, which is what makes a
~350-item slice fit inside Render's ~15 min request cap.

If a batch fails for any unexpected reason the job rolls it back and
reprocesses those same items through the **unchanged per-item route**
(``_write_items_individually``): a batch failure costs speed, never data.
Rows the batch route rejects up front (a NOT NULL missing, a string longer
than its column) are dropped individually and counted in ``errors`` — one
bad row never takes the slice down with it.

After a successful slice every job refreshes the catalog_search materialized
view so search results stay current.

Each job returns a dict with ``synced``, ``errors``, ``offset`` (the offset
of the processed slice), ``duration_s`` and ``people_errors`` so the admin
endpoint can expose the result synchronously. ``people_errors`` counts
failures persisting people/credits (cast, crew, authors) for an otherwise
successfully upserted item — those failures are logged but intentionally do
not increment ``errors`` (a missing credit must not abort the rest of the
slice), so ``people_errors`` is the only way to see them in
``POST /admin/sync/{type}``'s response.
"""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import text

from backlogg.books import repository as books_repo
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.books.service import collect_book_authors
from backlogg.core.config import settings
from backlogg.core.database import async_session_factory
from backlogg.core.metrics import get_metrics
from backlogg.games import repository as games_repo
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.movies import repository as movies_repo
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.service import collect_movie_credits
from backlogg.people import repository as people_repo
from backlogg.scheduler.repository import get_sync_offset, set_sync_offset
from backlogg.series import repository as series_repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.series.service import collect_series_creators, collect_series_credits
from backlogg.shared.bulk_load import (
    BulkItem,
    BulkLoadSpec,
    BulkPerson,
    bulk_load_items,
    rollback_quietly,
)
from backlogg.shared.external_ids import upsert_external_id

logger = logging.getLogger(__name__)

_tmdb_movies = TMDBClient()
_tmdb_series = TMDBSeriesClient()
_ol_client = OpenLibraryClient()
_igdb_client = IGDBClient()

# Per-type slice override (feature 84).  The global SYNC_SLICE_SIZE stays as
# the fallback so an environment that only sets it keeps working unchanged.
_SLICE_SETTING: dict[str, str] = {
    "MOVIE": "SYNC_SLICE_SIZE_MOVIES",
    "SERIES": "SYNC_SLICE_SIZE_SERIES",
    "BOOK": "SYNC_SLICE_SIZE_BOOKS",
    "GAME": "SYNC_SLICE_SIZE_GAMES",
}


async def _refresh_catalog_search(session) -> None:
    """Refresh the catalog_search materialized view concurrently."""
    await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search"))
    await session.commit()


def _resolve_slice_size(item_type: str, slice_size: int | None) -> int:
    """Resolve the slice size for ``item_type``.

    Order (feature 84): explicit argument -> ``SYNC_SLICE_SIZE_<TYPE>`` ->
    global ``SYNC_SLICE_SIZE``.  The per-type settings default to ``None``,
    so an untouched deployment behaves exactly as before.
    """
    if slice_size is not None:
        return slice_size
    per_type = getattr(settings, _SLICE_SETTING[item_type], None)
    if per_type is not None:
        return per_type
    return settings.SYNC_SLICE_SIZE


async def _read_slice(
    item_type: str, target: int, slice_size: int | None = None
) -> tuple[int, int]:
    """Return (offset, slice_size) for the next sync slice of ``item_type``.

    Reads the persisted cursor (0 if absent).  A stale cursor at or beyond
    ``target`` (e.g. after lowering SEED_TOP_N) is normalised back to 0.

    ``slice_size`` overrides the configured size when provided (used by the
    direct backfill script to process bigger slices without touching the
    production settings); otherwise ``_resolve_slice_size`` picks the
    per-type value, falling back to the global one.
    """
    size = _resolve_slice_size(item_type, slice_size)
    async with async_session_factory() as session:
        offset = await get_sync_offset(session, item_type)
    if offset >= target:
        offset = 0
    return offset, min(size, target - offset)


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


# ── Write path ───────────────────────────────────────────────────────────────


async def _persist_people_individually(
    session, item_type: str, item_id: int, people: list[BulkPerson]
) -> None:
    """Per-item people/credits write — the fallback's half of the batch route.

    Same two steps the on-demand path takes for a single item (resolve the
    person by external id, then upsert the credit), just driven by the rows
    the fetch phase already collected instead of re-hitting the external API.
    """
    now = datetime.now(UTC)
    for person in people:
        row = await people_repo.get_or_create_person_by_external(
            session,
            person.source,
            person.external_id,
            person.name,
            person.slug,
            person.profile_url,
            now,
        )
        if row is None:
            continue
        await people_repo.upsert_credit(
            session,
            {
                "item_type": item_type,
                "item_id": item_id,
                "person_id": row.id,
                "role": person.role,
                "character_name": person.character_name,
                "billing_order": person.billing_order,
            },
        )


async def _write_items_individually(
    session, spec: BulkLoadSpec, items: list[BulkItem], job_name: str
) -> tuple[int, int, int]:
    """Write ``items`` one at a time — the pre-feature-84 route, unchanged.

    Kept as the fallback for a batch that fails unexpectedly: each item is
    committed on its own and a per-item failure is rolled back, so a bad item
    can neither poison the shared session nor discard what is already
    persisted.  Returns ``(synced, errors, people_errors)``.
    """
    synced = 0
    errors = 0
    people_errors = 0
    for item in items:
        try:
            # The per-item upserts pop the relation keys off the dict they are
            # given, so hand them a copy and keep the batch payload intact.
            entity = await spec.upsert_item(session, dict(item.data))
            if item.external_id:
                await upsert_external_id(
                    session, spec.item_type, entity.id, spec.source, item.external_id
                )
            await session.commit()
            synced += 1
        except Exception:
            logger.exception(
                "%s: error upserting %s external_id=%s",
                job_name,
                spec.item_type,
                item.external_id,
            )
            errors += 1
            await rollback_quietly(session, job_name)
            continue

        if not item.people:
            continue
        try:
            await _persist_people_individually(session, spec.item_type, entity.id, item.people)
            await session.commit()
        except Exception:
            logger.exception(
                "%s: failed to persist people for external_id=%s", job_name, item.external_id
            )
            people_errors += 1
            await rollback_quietly(session, job_name)
    return synced, errors, people_errors


async def _write_batch(
    session, spec: BulkLoadSpec, items: list[BulkItem], job_name: str
) -> tuple[int, int, int]:
    """Write one batch through the bulk route, falling back per item on failure.

    Returns ``(synced, errors, people_errors)``.  Rows the bulk route rejects
    up front count as ``errors`` (they are items that did not make it in),
    rejected credits as ``people_errors`` — same reporting contract the
    per-item route has always had.
    """
    if not items:
        return 0, 0, 0
    try:
        outcome = await bulk_load_items(session, spec, items)
        await session.commit()
        # The batch wrote with raw SQL, so anything this session still holds in
        # its identity map is now stale; drop it (the nightly session holds
        # nothing, but callers that reuse a session must not read stale rows).
        session.expunge_all()
    except Exception:
        logger.exception(
            "%s: batch of %d items failed — retrying through the per-item route",
            job_name,
            len(items),
        )
        await rollback_quietly(session, job_name)
        return await _write_items_individually(session, spec, items, job_name)

    if outcome.rejected or outcome.people_rejected:
        logger.warning(
            "%s: batch dropped %d invalid rows and %d invalid credits",
            job_name,
            outcome.rejected,
            outcome.people_rejected,
        )
    return outcome.written, outcome.rejected, outcome.people_rejected


class _BatchWriter:
    """Accumulates fetched items and flushes them in ``BULK_LOAD_BATCH_SIZE`` chunks.

    Keeping the batch bounded caps both memory and the amount of work a
    single fallback has to redo.
    """

    def __init__(self, session, spec: BulkLoadSpec, job_name: str) -> None:
        self._session = session
        self._spec = spec
        self._job_name = job_name
        self._pending: list[BulkItem] = []
        self.synced = 0
        self.errors = 0
        self.people_errors = 0

    async def add(self, item: BulkItem) -> None:
        self._pending.append(item)
        if len(self._pending) >= max(1, settings.BULK_LOAD_BATCH_SIZE):
            await self.flush()

    async def flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        synced, errors, people_errors = await _write_batch(
            self._session, self._spec, batch, self._job_name
        )
        self.synced += synced
        self.errors += errors
        self.people_errors += people_errors


# ── Jobs ─────────────────────────────────────────────────────────────────────


async def sync_movies(slice_size: int | None = None) -> dict:
    """Fetch a slice of top popular movies from TMDB and upsert them locally.

    ``slice_size`` overrides ``settings.SYNC_SLICE_SIZE_MOVIES`` (which itself
    overrides the global ``settings.SYNC_SLICE_SIZE``) when provided.
    Returns a dict with keys ``synced``, ``errors``, ``people_errors``,
    ``offset`` and ``duration_s``.
    """
    logger.info("sync_movies: starting")
    get_metrics().inc_counter("backlogg_syncs_total", labels={"type": "movie"})
    start = time.monotonic()
    errors = 0
    people_errors = 0
    target = settings.SEED_TOP_N_MOVIES

    try:
        offset, slice_size = await _read_slice("MOVIE", target, slice_size)
    except Exception:
        logger.exception("sync_movies: failed to read sync cursor")
        return {
            "synced": 0,
            "errors": 1,
            "people_errors": 0,
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
            "people_errors": 0,
            "offset": offset,
            "duration_s": round(time.monotonic() - start, 1),
        }

    async with async_session_factory() as session:
        writer = _BatchWriter(session, movies_repo.MOVIE_BULK_SPEC, "sync_movies")
        for raw in raw_list:
            try:
                tmdb_id = raw.get("id")
                if not tmdb_id:
                    continue

                detail = await _tmdb_movies.get_movie_detail(tmdb_id)
                if detail is None:
                    continue

                movie_data = _tmdb_movies.movie_to_dict(detail)
            except Exception:
                logger.exception("sync_movies: error fetching tmdb_id=%s", raw.get("id"))
                errors += 1
                continue

            try:
                people = await collect_movie_credits(tmdb_id)
            except Exception:
                # A credits failure must not cost the item itself.
                logger.exception("sync_movies: failed to fetch credits for tmdb_id=%s", tmdb_id)
                people_errors += 1
                people = []

            await writer.add(BulkItem(data=movie_data, external_id=str(tmdb_id), people=people))
        await writer.flush()

        await _persist_cursor(
            session, "MOVIE", _next_offset(offset, len(raw_list), slice_size, target), "sync_movies"
        )

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_movies: failed to refresh catalog_search")

    synced = writer.synced
    errors += writer.errors
    people_errors += writer.people_errors
    logger.info(
        "sync_movies: done — %d items upserted, %d errors, %d people_errors (offset %d)",
        synced,
        errors,
        people_errors,
        offset,
    )
    return {
        "synced": synced,
        "errors": errors,
        "people_errors": people_errors,
        "offset": offset,
        "duration_s": round(time.monotonic() - start, 1),
    }


async def sync_series(slice_size: int | None = None) -> dict:
    """Fetch a slice of popular TV series from TMDB and upsert them locally.

    ``slice_size`` overrides ``settings.SYNC_SLICE_SIZE_SERIES`` (which itself
    overrides the global ``settings.SYNC_SLICE_SIZE``) when provided.
    Returns a dict with keys ``synced``, ``errors``, ``people_errors``,
    ``offset`` and ``duration_s``.
    """
    logger.info("sync_series: starting")
    get_metrics().inc_counter("backlogg_syncs_total", labels={"type": "series"})
    start = time.monotonic()
    errors = 0
    people_errors = 0
    target = settings.SEED_TOP_N_SERIES

    try:
        offset, slice_size = await _read_slice("SERIES", target, slice_size)
    except Exception:
        logger.exception("sync_series: failed to read sync cursor")
        return {
            "synced": 0,
            "errors": 1,
            "people_errors": 0,
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
            "people_errors": 0,
            "offset": offset,
            "duration_s": round(time.monotonic() - start, 1),
        }

    async with async_session_factory() as session:
        writer = _BatchWriter(session, series_repo.SERIES_BULK_SPEC, "sync_series")
        for raw in raw_list:
            try:
                tmdb_id = raw.get("id")
                if not tmdb_id:
                    continue

                detail = await _tmdb_series.get_series_detail(tmdb_id)
                if detail is None:
                    continue

                series_data = _tmdb_series.series_to_dict(detail)
            except Exception:
                logger.exception("sync_series: error fetching tmdb_id=%s", raw.get("id"))
                errors += 1
                continue

            try:
                people = await collect_series_credits(tmdb_id)
                people += collect_series_creators(detail.get("created_by", []))
            except Exception:
                logger.exception("sync_series: failed to fetch credits for tmdb_id=%s", tmdb_id)
                people_errors += 1
                people = []

            await writer.add(BulkItem(data=series_data, external_id=str(tmdb_id), people=people))
        await writer.flush()

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

    synced = writer.synced
    errors += writer.errors
    people_errors += writer.people_errors
    logger.info(
        "sync_series: done — %d items upserted, %d errors, %d people_errors (offset %d)",
        synced,
        errors,
        people_errors,
        offset,
    )
    return {
        "synced": synced,
        "errors": errors,
        "people_errors": people_errors,
        "offset": offset,
        "duration_s": round(time.monotonic() - start, 1),
    }


async def sync_books(slice_size: int | None = None) -> dict:
    """Fetch a slice of popular books from Open Library and upsert them locally.

    ``slice_size`` overrides ``settings.SYNC_SLICE_SIZE_BOOKS`` (which itself
    overrides the global ``settings.SYNC_SLICE_SIZE``) when provided.
    Returns a dict with keys ``synced``, ``errors``, ``people_errors``,
    ``offset`` and ``duration_s``.
    """
    logger.info("sync_books: starting")
    get_metrics().inc_counter("backlogg_syncs_total", labels={"type": "book"})
    start = time.monotonic()
    errors = 0
    people_errors = 0
    target = settings.SEED_TOP_N_BOOKS

    try:
        offset, slice_size = await _read_slice("BOOK", target, slice_size)
    except Exception:
        logger.exception("sync_books: failed to read sync cursor")
        return {
            "synced": 0,
            "errors": 1,
            "people_errors": 0,
            "offset": 0,
            "duration_s": round(time.monotonic() - start, 1),
        }

    try:
        raw_list = await _ol_client.get_popular_books(limit=slice_size, offset=offset)
    except Exception:
        logger.exception("sync_books: failed to fetch from Open Library")
        return {
            "synced": 0,
            "errors": 1,
            "people_errors": 0,
            "offset": offset,
            "duration_s": round(time.monotonic() - start, 1),
        }

    async with async_session_factory() as session:
        writer = _BatchWriter(session, books_repo.BOOK_BULK_SPEC, "sync_books")
        for raw in raw_list:
            try:
                work_key = raw.get("key", "")
                work_id = work_key.removeprefix("/works/") if work_key else None

                # ⚠️ This search_doc is rebuilt by hand instead of passing
                # ``raw`` straight through, so every field book_to_dict reads
                # must be copied here explicitly. Forgetting one silently
                # degrades the nightly job while the on-demand path keeps
                # working (that was Issue #17 with ``isbn``). Keep in sync
                # with ``_OL_SEARCH_FIELDS`` in the Open Library adapter.
                # ``edition_count`` is in that field set but deliberately not
                # copied: it is the feature-73 seed filter's discriminant,
                # requested only so a page can be audited, and book_to_dict
                # never reads it — copying it would add a dead key.
                search_doc: dict = {
                    "title": raw.get("title", ""),
                    "key": work_key,
                    "first_publish_year": raw.get("first_publish_year"),
                    "cover_i": raw.get("cover_i") or raw.get("cover_id"),
                    "author_name": raw.get("author_name", []),
                    "isbn": raw.get("isbn", []),
                    "ddc": raw.get("ddc", []),
                    "lcc": raw.get("lcc", []),
                    "subject_facet": raw.get("subject_facet", []),
                }

                book_data = _ol_client.book_to_dict(search_doc, None)
                if not book_data.get("title"):
                    continue
            except Exception:
                logger.exception("sync_books: error mapping work_key=%s", raw.get("key"))
                errors += 1
                continue

            people: list[BulkPerson] = []
            if work_id:
                try:
                    work_detail = await _ol_client.get_work_detail(work_id)
                    if work_detail:
                        people = await collect_book_authors(work_detail)
                except Exception:
                    logger.exception("sync_books: failed to fetch authors for work_id=%s", work_id)
                    people_errors += 1

            await writer.add(BulkItem(data=book_data, external_id=work_id, people=people))
        await writer.flush()

        await _persist_cursor(
            session, "BOOK", _next_offset(offset, len(raw_list), slice_size, target), "sync_books"
        )

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_books: failed to refresh catalog_search")

    synced = writer.synced
    errors += writer.errors
    people_errors += writer.people_errors
    logger.info(
        "sync_books: done — %d items upserted, %d errors, %d people_errors (offset %d)",
        synced,
        errors,
        people_errors,
        offset,
    )
    return {
        "synced": synced,
        "errors": errors,
        "people_errors": people_errors,
        "offset": offset,
        "duration_s": round(time.monotonic() - start, 1),
    }


async def sync_games(slice_size: int | None = None) -> dict:
    """Fetch a slice of top-rated games from IGDB and upsert them locally.

    ``slice_size`` overrides ``settings.SYNC_SLICE_SIZE_GAMES`` (which itself
    overrides the global ``settings.SYNC_SLICE_SIZE``) when provided.
    Returns a dict with keys ``synced``, ``errors``, ``offset`` and
    ``duration_s``.
    """
    logger.info("sync_games: starting")
    get_metrics().inc_counter("backlogg_syncs_total", labels={"type": "game"})
    start = time.monotonic()
    errors = 0
    target = settings.SEED_TOP_N_GAMES

    try:
        offset, slice_size = await _read_slice("GAME", target, slice_size)
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
        writer = _BatchWriter(session, games_repo.GAME_BULK_SPEC, "sync_games")
        for raw in raw_list:
            try:
                igdb_id = raw.get("id")
                if not igdb_id:
                    continue

                game_data = _igdb_client.game_to_dict(raw)
            except Exception:
                logger.exception("sync_games: error mapping igdb_id=%s", raw.get("id"))
                errors += 1
                continue

            # Games carry no people: developers/publishers are company credits
            # and travel inside ``game_data`` itself.
            await writer.add(BulkItem(data=game_data, external_id=str(igdb_id)))
        await writer.flush()

        await _persist_cursor(
            session, "GAME", _next_offset(offset, len(raw_list), slice_size, target), "sync_games"
        )

        try:
            await _refresh_catalog_search(session)
        except Exception:
            logger.exception("sync_games: failed to refresh catalog_search")

    synced = writer.synced
    errors += writer.errors
    logger.info(
        "sync_games: done — %d items upserted, %d errors (offset %d)", synced, errors, offset
    )
    return {
        "synced": synced,
        "errors": errors,
        "offset": offset,
        "duration_s": round(time.monotonic() - start, 1),
    }
