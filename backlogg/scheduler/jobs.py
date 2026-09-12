"""Scheduler jobs — nightly sync for each content type.

Each job is an independent async coroutine.  Errors are logged but never
propagated so that a failure in one job does not abort the others.

Two enumeration models live here since feature 86:

* **Books** keep the original one: each run processes a slice of the external
  API's popular listing, reading the persisted cursor for its type from
  ``sync_cursors`` (0 if absent), fetching up to the type's slice size
  starting at that offset (never beyond ``settings.SEED_TOP_N_BOOKS``) and
  advancing the cursor at the end.  The cursor wraps around to 0 when the
  target is reached or when the API returns fewer items than requested.
  Books are the *last* type on this model and it is not a good one: the
  wraparound target caps the catalog below what the quality filter selects
  (issue #27, still open — it is closed by moving the nightly book walk off
  the cursor, not by anything in feature 90).
* **Movies, series and games** are driven by the enumerated target list in
  ``seed_targets`` instead (features 86 and 90).  There is no cursor and no
  offset: the work list is the *difference* between what the catalog wants
  and what it has, and once that difference is empty the slice is filled by
  ``last_synced_at`` rotation.  See the sections at the bottom of this file.
  The two halves differ only in the fetch: TMDB has no bulk detail endpoint
  and pays one request per item, while IGDB answers ``where id = (...)`` with
  up to 500 fully-hydrated games in a single request.

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

Nothing is refreshed after a slice: since feature 91 ``search_vector`` is a
generated column on the four content tables, so every item a slice writes is
searchable the moment the slice's transaction commits.  The
``catalog_search`` materialized view — and the ``REFRESH MATERIALIZED VIEW
CONCURRENTLY`` that used to close each job — are gone (issue #28).

Besides the four sync jobs this module exposes the three **incremental** jobs
of feature 88 (``sync_movies_incremental``, ``sync_series_incremental`` and
``sync_games_incremental``).  They are not slices of the nightly walk: they ask
each source what changed since the last run and resume from a cursor persisted
in ``sync_watermarks``.

* TMDB runs three lanes: new ids from the daily id export (gated on the release
  date, since a release has no votes yet), a promotion sweep that re-enumerates
  recent years so items crossing ``vote_count >= 25`` after the seeding still
  enter, and ``/movie/changes``/``/tv/changes`` to re-hydrate what the catalog
  already holds.
* IGDB runs three, the same shape: ``where created_at > <watermark>`` for new
  games (gated on the ``game_type`` allowlist, which is the only bar a game
  released today *can* clear), ``where updated_at > <watermark>`` to refresh
  the ones the catalog already holds, and a promotion sweep that re-enumerates
  the whole catalog filter by keyset so a game that had no rating when the
  catalog was enumerated and has one now still enters.  That third lane closed
  issue #34: the mechanism was always the same as TMDB's (re-enumerate, then
  hydrate the difference), but until then the *trigger* was a person running
  ``scripts/seed_igdb_targets.py``, so the promotion delay was the gap between
  two human decisions instead of a day.  The script stays as the manual and
  resumable route (``--start-after``); it is no longer the only one.

Books are not here: their incremental is a diff of Open Library's *monthly*
dump and belongs to the script layer (``scripts/incremental_sync.py``), for the
same reason the seeding does — it is 17,5 GB of streaming, not a job.  See the
sections further down this file.

This module also exposes ``sync_missing_credits``
(feature 85): a *targeted* pass whose work list comes from the local catalog
(``LEFT JOIN credits ... WHERE NULL``) instead of the popularity ranking,
used to close credit holes the ranking route structurally cannot reach
(issue #15).  See the section at the bottom of this file.

Each job returns a dict with ``synced``, ``errors``, ``offset`` (the offset
of the processed slice), ``duration_s``, ``people_errors`` and
``skipped_links`` so the admin endpoint can expose the result synchronously.
``people_errors`` counts failures persisting people/credits (cast, crew,
authors) for an otherwise successfully upserted item — those failures are
logged but intentionally do not increment ``errors`` (a missing credit must
not abort the rest of the slice), so ``people_errors`` is the only way to see
them in ``POST /admin/sync/{type}``'s response.

``skipped_links`` (issue #22) counts the ``external_ids`` rows this run wanted
to write and could not because the ``(item_type, source, external_id)`` triple
was already claimed by a *different* item of the same type — the item lands in
its table with no link, so it is invisible to every id-based lookup afterwards.
Idempotent re-offers of a link that already points at the same item are **not**
counted. Both write paths feed it through the ``collect_link_skips()``
accumulator in ``backlogg.shared.external_ids``; the job only opens the block
and reads the total. It is the panel light for a seeding run: a number that
grows slice after slice means catalog is being dropped *while* the run is
still going, which is exactly what issues #7, #15 and #20 each cost months to
notice.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial

from backlogg.books import repository as books_repo
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.books.service import collect_book_authors
from backlogg.core.config import settings
from backlogg.core.database import async_session_factory
from backlogg.core.metrics import get_metrics
from backlogg.games import repository as games_repo
from backlogg.games.adapters.igdb import IGDB_PAGE_SIZE, IGDBClient, parse_igdb_timestamp
from backlogg.games.constants import (
    ALLOWED_GAME_CATEGORY_IDS,
    ALLOWED_GAME_TYPES,
    GAME_TYPE_MAP,
)
from backlogg.movies import repository as movies_repo
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.service import collect_movie_credits, map_movie_credits
from backlogg.people import repository as people_repo
from backlogg.scheduler.discovery import (
    MAX_DISCOVER_PAGES,
    DiscoveredTarget,
    ReleaseGate,
    enumerate_windows,
    fetch_change_ids,
    plan_change_windows,
    release_gate_verdict,
    year_windows,
)
from backlogg.scheduler.igdb_catalog import IgdbEnumerationStats, enumerate_catalog
from backlogg.scheduler.repository import (
    CREDIT_GAP_SOURCES,
    SEED_TARGET_SOURCES,
    CreditGap,
    SeedTargetProgress,
    SeedTargetRow,
    Watermark,
    count_seed_target_progress,
    filter_catalogued_external_ids,
    get_credit_gaps,
    get_known_source_ids,
    get_pending_seed_targets,
    get_stale_catalog_external_ids,
    get_sync_offset,
    get_sync_watermark,
    mark_credits_synced,
    mark_seed_targets_attempted,
    mark_seed_targets_unreachable,
    set_sync_offset,
    set_sync_watermark,
    upsert_seed_targets,
)
from backlogg.scheduler.tmdb_exports import (
    EXPORT_MOVIES,
    EXPORT_SERIES,
    ExportUnavailable,
    collect_appeared_entries,
    latest_export_date,
    load_export_ids,
)
from backlogg.series import repository as series_repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.series.service import collect_series_creators, map_series_credits
from backlogg.shared.bulk_load import (
    BulkItem,
    BulkLoadSpec,
    BulkPerson,
    bulk_load_credits,
    bulk_load_items,
    rollback_quietly,
)
from backlogg.shared.credits import CAST_ROLE, build_cast_payload, upsert_item_cast
from backlogg.shared.external_ids import collect_link_skips, upsert_external_id
from backlogg.shared.identity import resolve_item_slug

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

# CLI/content name -> polymorphic item_type used across the schema.
_ITEM_TYPES_BY_CONTENT: dict[str, str] = {
    "movie": "MOVIE",
    "series": "SERIES",
    "book": "BOOK",
    "game": "GAME",
}


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

    ⚠️ **Books only** since feature 90.  Movies and series left the cursor in
    feature 86 and games in feature 90; ``sync_books`` is the single caller
    left, and it stays here rather than being inlined because the cursor walk
    is unchanged and issue #27 will retire it whole.

    Reads the persisted cursor (0 if absent).  A stale cursor at or beyond
    ``target`` (e.g. after lowering SEED_TOP_N_BOOKS) is normalised back to 0.

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

    Takes the same fork as every other write path since feature 89: the cast
    (``CAST_ROLE``) becomes one ``item_cast`` array and creates no ``people``,
    ``external_ids`` or ``credits`` row; the crew builds the graph as before.
    """
    now = datetime.now(UTC)

    payload = build_cast_payload(
        (person.name, person.character_name, person.billing_order)
        for person in people
        if person.role == CAST_ROLE
    )
    if payload:
        await upsert_item_cast(session, item_type, [(item_id, payload)])

    for person in people:
        if person.role == CAST_ROLE:
            continue
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
            if not item.data.get("slug"):
                # Same issue #18 invariant the batch route enforces: an empty
                # slug is the ON CONFLICT key, so it would merge unrelated
                # items into one row.  Raising here lands in the ``except``
                # below, which logs it and counts it in ``errors``.
                raise ValueError(
                    f"{spec.item_type}: empty slug — the title folds to nothing "
                    "and the payload carries no external id"
                )
            # The per-item upserts pop the relation keys off the dict they are
            # given, so hand them a copy and keep the batch payload intact.
            data = dict(item.data)
            if item.external_id:
                # Issue #23, same rule the batch route applies before its COPY:
                # the external id decides which row this is, so a renamed item
                # updates its own row instead of forking an unlinkable twin.
                # Done here rather than inside ``spec.upsert_item`` because the
                # spec's callable is the pre-existing ``upsert_*(db, data)``
                # signature the batch loader shares with the on-demand route.
                data["slug"] = await resolve_item_slug(
                    session,
                    item_type=spec.item_type,
                    table=spec.table,
                    source=spec.source,
                    external_id=item.external_id,
                    proposed_slug=data["slug"],
                )
            entity = await spec.upsert_item(session, data)
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


class BatchWriter:
    """Accumulates fetched items and flushes them in ``BULK_LOAD_BATCH_SIZE`` chunks.

    Keeping the batch bounded caps both memory and the amount of work a
    single fallback has to redo.  Each flush commits, which is also what makes
    a long seeding run resumable: whatever landed stays landed.

    Public (rather than ``_``-prefixed) because the write path is shared: the
    nightly jobs here and ``scripts/seed_openlibrary_books.py`` (feature 87)
    must write through the *same* batching-with-per-item-fallback code, not
    through two copies of it.
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


# ── TMDB jobs: target-driven hydration (feature 86) ───────────────────────────
#
# ``sync_movies``/``sync_series`` used to walk ``/movie/popular`` and
# ``/tv/popular`` by offset.  That is gone, for the three reasons
# ``docs/seeding-plan.md`` §1 measures: the listing caps at 10.000 items, it
# reorders itself while being paginated (so the offset walk does not even
# cover those 10.000), and ``popularity`` ranks *recent interest* rather than
# notoriety.  The catalog is now defined by a ``vote_count`` threshold,
# enumerated into ``seed_targets`` by ``scripts/seed_tmdb_targets.py``.
#
# What a slice does, in order:
#
# 1. **Pending targets first.**  ``get_pending_seed_targets`` is the
#    difference between the enumerated target list and ``external_ids`` — the
#    resume mechanism.  No offset, no progress marker: whatever a crashed run
#    left undone is exactly what the next one picks up.
# 2. **Retirement, so that "nothing is pending" is reachable.**  Some targets
#    can never link: TMDB may answer 404 for an enumerated id, and a fetch that
#    resolves is still no guarantee of a link — two ids whose title and year
#    slugify to the same value share one row and only one keeps its link
#    (before migration 0036 the common shape was different: ``uq_external_id``
#    had no ``item_type``, so a PERSON id blocked a movie or a series —
#    issue #20).  Left in place they would occupy a slot of
#    every slice forever and hold ``pending`` above 0 permanently.  A 404 is
#    stamped in ``unreachable_at`` on first sight; a target that keeps
#    resolving without linking is retired after ``TMDB_SEED_MAX_ATTEMPTS``
#    *conclusive* passes (a failed fetch does not count, so an outage cannot
#    retire a healthy target).  The residue is not hidden: it comes back as
#    ``stuck`` in the result and as a warning in the log.
# 3. **Refresh rotation to fill the rest.**  Once nothing is pending the slice
#    is filled with the catalog items whose ``last_synced_at`` is oldest.
#    Without this the removal of the cursor would have *lost* something the
#    old walk provided as a side effect: TMDB forbids caching its data beyond
#    6 months (``docs/seeding-plan.md`` §2.3), and the wrapping cursor was
#    what eventually revisited everything.  Rotating by ``last_synced_at`` is
#    the same guarantee, stated directly instead of emerging from a ranking.
#    It only works because of step 2.
# 4. **One request per item.**  ``append_to_response=credits,external_ids``
#    folds what used to be a second ``/{id}/credits`` call into the detail
#    request, halving the HTTP of a full catalog pass.
# 5. **Parallel fetch, sequential write.**  ``asyncio.gather`` under a
#    ``Semaphore`` (``TMDB_SEED_CONCURRENCY``, default 8 ≈ 32 req/s against
#    TMDB's ~50 limit), then the feature-84 batch writer — ``AsyncSession`` is
#    not safe for concurrent use.
#
# ``SEED_TOP_N_MOVIES``/``SEED_TOP_N_SERIES`` take no part in any of this: the
# catalog is defined by ``TMDB_SEED_MIN_VOTES_*`` and the nightly volume by
# ``SYNC_SLICE_SIZE_*``.  See ``backlogg/core/config.py``.

# Sub-resources folded into the detail request.  ``credits`` is what feeds the
# people/credits rows (cast, director and the feature-74 writing crew).
# ``external_ids`` is not read by any code path yet — feature 74 turned out to
# need only ``credits`` — but it rides along for free in the same request.
_TMDB_APPEND_TO_RESPONSE = "credits,external_ids"


async def _fetch_movie_detail(external_id: str) -> dict | None:
    """The raw TMDB movie detail payload, credits appended. None on a 404.

    Split from ``_fetch_movie_payload`` for feature 88: the release gate of the
    incremental has to read the *raw* payload (``adult``, ``video``, ``status``
    and the release date as TMDB spells it), and mapping a payload that is
    about to be rejected would be work spent on nothing.
    """
    return await _tmdb_movies.get_movie_detail(
        int(external_id), append_to_response=_TMDB_APPEND_TO_RESPONSE
    )


def _map_movie_detail(detail: dict) -> tuple[dict, list[BulkPerson]]:
    """Map a raw movie detail into the write payload and its people."""
    return _tmdb_movies.movie_to_dict(detail), map_movie_credits(detail.get("credits"))


async def _fetch_series_detail(external_id: str) -> dict | None:
    """The raw TMDB series detail payload, credits appended. None on a 404."""
    return await _tmdb_series.get_series_detail(
        int(external_id), append_to_response=_TMDB_APPEND_TO_RESPONSE
    )


def _map_series_detail(detail: dict) -> tuple[dict, list[BulkPerson]]:
    """Map a raw series detail into the write payload and its people.

    CREATOR credits come from ``created_by``, which lives in the detail body
    and not in ``/tv/{id}/credits`` — so the single request is strictly more
    informative than the two it replaces, not just cheaper.
    """
    people = map_series_credits(detail.get("credits"))
    people += collect_series_creators(detail.get("created_by", []))
    return _tmdb_series.series_to_dict(detail), people


async def _fetch_movie_payload(external_id: str) -> tuple[dict, list[BulkPerson]] | None:
    """Detail + credits for one movie in a single request. None on a 404."""
    detail = await _fetch_movie_detail(external_id)
    if detail is None:
        return None
    return _map_movie_detail(detail)


async def _fetch_series_payload(external_id: str) -> tuple[dict, list[BulkPerson]] | None:
    """Detail + cast + creators for one series in a single request. None on a 404."""
    detail = await _fetch_series_detail(external_id)
    if detail is None:
        return None
    return _map_series_detail(detail)


@dataclass(frozen=True, slots=True)
class _TmdbSeedSpec:
    """The three things that differ between the movie and the series job."""

    item_type: str
    job_name: str
    metric_label: str
    bulk_spec: BulkLoadSpec
    fetch: Callable[[str], Awaitable[tuple[dict, list[BulkPerson]] | None]]


def _movie_seed_spec() -> _TmdbSeedSpec:
    return _TmdbSeedSpec(
        item_type="MOVIE",
        job_name="sync_movies",
        metric_label="movie",
        bulk_spec=movies_repo.MOVIE_BULK_SPEC,
        fetch=_fetch_movie_payload,
    )


def _series_seed_spec() -> _TmdbSeedSpec:
    return _TmdbSeedSpec(
        item_type="SERIES",
        job_name="sync_series",
        metric_label="series",
        bulk_spec=series_repo.SERIES_BULK_SPEC,
        fetch=_fetch_series_payload,
    )


async def _read_seed_work_list(
    item_type: str, source: str, slice_size: int
) -> tuple[list[str], list[str], SeedTargetProgress]:
    """Return ``(pending_ids, refresh_ids, progress)`` for one slice.

    The two lists are disjoint by construction: pending targets are the ones
    *without* an ``external_ids`` row and the refresh rotation only walks
    items that have one.

    The rotation fills whatever the pending targets leave over.  That is only
    a real guarantee because ``pending`` is *workable* pending: retired
    targets (404 at TMDB, or an id another item type already claimed) are out
    of both the list and the count, so the condition below can actually be
    met.  Before retirement existed, a permanent floor of unlinkable targets
    would have kept this branch from ever running — and with it TMDB's
    6-month cache-window obligation from ever being met.
    """
    max_attempts = _seed_max_attempts()
    async with async_session_factory() as session:
        progress = await count_seed_target_progress(session, item_type, source, max_attempts)
        pending = await get_pending_seed_targets(
            session, item_type, source, slice_size, max_attempts
        )
        refresh: list[str] = []
        if len(pending) < slice_size:
            refresh = await get_stale_catalog_external_ids(
                session, item_type, source, slice_size - len(pending)
            )
    return pending, refresh, progress


async def _fetch_seed_item_guarded(
    sem: asyncio.Semaphore, spec: _TmdbSeedSpec, external_id: str
) -> tuple[dict, list[BulkPerson]] | None:
    """Fetch one item under *sem*; exceptions propagate to ``gather``."""
    async with sem:
        return await spec.fetch(external_id)


def _seed_max_attempts() -> int:
    """Conclusive passes a seed target gets before it is retired.

    One knob for every target-driven type.  The name is historical — it was
    introduced by feature 86, when TMDB was the only source with a target
    list — and it was deliberately *not* renamed in feature 90: it is exported
    as an environment variable on Render, and renaming a deployed variable
    silently falls back to the default instead of failing loudly.  What it
    means is source-independent: how many times a target may resolve without
    ever producing an ``external_ids`` row before it stops costing a slice
    slot every single night.
    """
    return max(1, settings.TMDB_SEED_MAX_ATTEMPTS)


def _seed_result(
    start: float,
    *,
    synced: int,
    errors: int,
    people_errors: int,
    skipped_links: int,
    progress: SeedTargetProgress,
    refreshed: int,
) -> dict:
    """The result dict every target-driven slice returns.

    Shared by ``_sync_tmdb_type`` and ``sync_games`` so the two cannot drift:
    ``POST /admin/sync/{type}`` (``SyncResponse``) and
    ``scripts/backfill_sync.py`` read these keys by name, and the loop of the
    latter stops on ``pending``.

    ``offset`` is a constant 0.  There is no cursor behind these types any
    more, but the field is declared required in ``SyncResponse`` and dropping
    it would turn a 200 into a 500.
    """
    return {
        "synced": synced,
        "errors": errors,
        "people_errors": people_errors,
        "skipped_links": skipped_links,
        "offset": 0,
        "duration_s": round(time.monotonic() - start, 1),
        "pending": progress.pending,
        "stuck": progress.stuck,
        "refreshed": refreshed,
    }


async def _stamp_seed_outcomes(
    session,
    item_type: str,
    source: str,
    resolved: Sequence[str],
    gone: Sequence[str],
    job_name: str,
) -> None:
    """Book-keeping for the pending targets a slice worked on conclusively.

    Shared by both target-driven jobs, which is the point: counting only
    conclusive outcomes is what makes retirement safe (an outage costs a
    target nothing, while a target that keeps resolving and never linking runs
    out of passes and leaves the work list), and a second copy of that rule
    would eventually disagree with this one.

    ``resolved`` are targets whose fetch came back with a payload; ``gone``
    the ones the source no longer serves.  Commits, and a failure to stamp is
    logged and rolled back rather than raised: the items of the slice are
    already written, and losing the whole slice over its book-keeping would be
    a worse trade than re-attempting those targets next run.
    """
    try:
        now = datetime.now(UTC)
        await mark_seed_targets_attempted(session, item_type, source, resolved, now)
        await mark_seed_targets_unreachable(session, item_type, source, gone, now)
        await session.commit()
    except Exception:
        logger.exception("%s: failed to stamp seed target outcomes", job_name)
        await rollback_quietly(session, job_name)


async def _recount_seed_progress(
    session, item_type: str, source: str, fallback: SeedTargetProgress, job_name: str
) -> SeedTargetProgress:
    """Re-read the target progress after a slice, or keep ``fallback``."""
    try:
        return await count_seed_target_progress(session, item_type, source, _seed_max_attempts())
    except Exception:
        logger.exception("%s: failed to recount seed target progress", job_name)
        return fallback


def _seed_failure_result(start: float) -> dict:
    """Result dict for a slice that could not even build its work list.

    ``pending`` and ``stuck`` are ``None``, not 0: the work list could not be
    read, so how much work is left is *unknown*.  Reporting 0 would tell every
    consumer — the log line, the backfill loop's stop condition — that the
    catalog is complete because the database was down.
    """
    return {
        "synced": 0,
        "errors": 1,
        "people_errors": 0,
        "skipped_links": 0,
        "offset": 0,
        "duration_s": round(time.monotonic() - start, 1),
        "pending": None,
        "stuck": None,
        "refreshed": 0,
    }


async def _sync_tmdb_type(spec: _TmdbSeedSpec, slice_size: int | None = None) -> dict:
    """Hydrate one slice of ``spec.item_type`` from the enumerated target list.

    Returns the same keys the ranking jobs return — ``synced``, ``errors``,
    ``people_errors``, ``offset`` and ``duration_s``, which is the contract
    ``POST /admin/sync/{type}`` and ``.github/workflows/nightly-sync.yml``
    consume — plus ``pending`` and ``refreshed``.

    ``offset`` is kept at a constant 0: there is no cursor behind these two
    types any more, but ``SyncResponse`` declares the field as required and
    silently dropping it would turn a 200 into a 500.  ``pending`` (workable
    targets still missing from the catalog after this slice) is what replaces
    it as the progress signal, and it is what ``scripts/backfill_sync.py``
    loops on; ``stuck`` is the residue that was retired from the work list and
    will not come back on its own.
    """
    logger.info("%s: starting", spec.job_name)
    get_metrics().inc_counter("backlogg_syncs_total", labels={"type": spec.metric_label})
    start = time.monotonic()
    source = SEED_TARGET_SOURCES[spec.item_type]
    size = max(1, _resolve_slice_size(spec.item_type, slice_size))

    try:
        pending, refresh, progress = await _read_seed_work_list(spec.item_type, source, size)
    except Exception:
        logger.exception("%s: failed to read the seed work list", spec.job_name)
        return _seed_failure_result(start)

    work = pending + refresh
    logger.info(
        "%s: %d workable target(s) pending (%d gone from TMDB, %d unlinkable) — this "
        "slice takes %d of them plus %d refresh item(s) by oldest last_synced_at",
        spec.job_name,
        progress.pending,
        progress.gone,
        progress.unlinkable,
        len(pending),
        len(refresh),
    )
    if not work:
        logger.info("%s: nothing to do — no pending targets and an empty catalog", spec.job_name)
        return _seed_result(
            start,
            synced=0,
            errors=0,
            people_errors=0,
            skipped_links=0,
            progress=progress,
            refreshed=0,
        )

    sem = asyncio.Semaphore(max(1, settings.TMDB_SEED_CONCURRENCY))
    chunk_size = max(1, settings.BULK_LOAD_BATCH_SIZE)
    errors = 0
    # Targets from the pending list whose fetch reached a *conclusive* answer,
    # split by which answer.  A fetch that raised belongs to neither: it is
    # retried next run without spending any of the target's budget.
    resolved: list[str] = []
    gone: list[str] = []
    pending_targets = set(pending)

    with collect_link_skips() as link_skips:
        async with async_session_factory() as session:
            writer = BatchWriter(session, spec.bulk_spec, spec.job_name)
            for chunk_start in range(0, len(work), chunk_size):
                chunk = work[chunk_start : chunk_start + chunk_size]

                # Fetch phase — parallel, bounded by the semaphore.
                fetched = await asyncio.gather(
                    *(_fetch_seed_item_guarded(sem, spec, external_id) for external_id in chunk),
                    return_exceptions=True,
                )

                # Persist phase — sequential: AsyncSession is not concurrency-safe.
                for external_id, outcome in zip(chunk, fetched, strict=True):
                    if isinstance(outcome, BaseException):
                        logger.warning(
                            "%s: fetch failed for external_id=%s (%s) — not counted as an "
                            "attempt, will retry next run",
                            spec.job_name,
                            external_id,
                            outcome,
                        )
                        errors += 1
                        continue
                    if outcome is None:
                        # 404 at TMDB: the id was enumerated but has since been
                        # deleted or merged. Not an error — nothing to write, and
                        # a definitive answer, so the target is retired now rather
                        # than re-asked on every future run.
                        logger.info(
                            "%s: external_id=%s is gone from TMDB (404) — retiring the target",
                            spec.job_name,
                            external_id,
                        )
                        if external_id in pending_targets:
                            gone.append(external_id)
                        continue
                    data, people = outcome
                    if external_id in pending_targets:
                        resolved.append(external_id)
                    await writer.add(BulkItem(data=data, external_id=external_id, people=people))
                await writer.flush()

            await _stamp_seed_outcomes(
                session, spec.item_type, source, resolved, gone, spec.job_name
            )
            after = await _recount_seed_progress(
                session, spec.item_type, source, progress, spec.job_name
            )

    synced = writer.synced
    errors += writer.errors
    people_errors = writer.people_errors
    skipped_links = link_skips.count
    logger.info(
        "%s: done — %d items upserted, %d errors, %d people_errors, %d skipped_links, "
        "%d gone from TMDB (%d targets still pending, %d stuck: %d gone, %d unlinkable)",
        spec.job_name,
        synced,
        errors,
        people_errors,
        skipped_links,
        len(gone),
        after.pending,
        after.stuck,
        after.gone,
        after.unlinkable,
    )
    if after.unlinkable:
        # Not a failure of this run, but the operator has to be able to see it:
        # these targets resolve at TMDB and still never end up with an
        # external_ids row (docs/schema.md).
        logger.warning(
            "%s: %d target(s) retired as unlinkable after %d conclusive passes — they "
            "resolve at the source but never get an external_ids row",
            spec.job_name,
            after.unlinkable,
            _seed_max_attempts(),
        )
    return _seed_result(
        start,
        synced=synced,
        errors=errors,
        people_errors=people_errors,
        skipped_links=skipped_links,
        progress=after,
        refreshed=len(refresh),
    )


async def sync_movies(slice_size: int | None = None) -> dict:
    """Hydrate a slice of the enumerated movie catalog from TMDB.

    Work list: the movie targets in ``seed_targets`` that the catalog does not
    have yet (``TMDB_SEED_MIN_VOTES_MOVIES`` decides which items are targets
    at all), topped up by the least recently synced movies once none are
    pending.  ``slice_size`` overrides ``settings.SYNC_SLICE_SIZE_MOVIES``
    (which itself overrides the global ``settings.SYNC_SLICE_SIZE``).

    Returns a dict with ``synced``, ``errors``, ``people_errors``, ``offset``
    (always 0 — no cursor), ``duration_s``, ``pending`` (workable targets left),
    ``stuck`` (targets retired as unreachable/unlinkable) and ``refreshed``.
    """
    return await _sync_tmdb_type(_movie_seed_spec(), slice_size)


async def sync_series(slice_size: int | None = None) -> dict:
    """Hydrate a slice of the enumerated series catalog from TMDB.

    Same shape as ``sync_movies``, with ``TMDB_SEED_MIN_VOTES_SERIES`` and
    ``settings.SYNC_SLICE_SIZE_SERIES``.  Series need a far smaller nightly
    slice than movies (10.880 items against 57.135, so ~61/night against ~318
    to stay inside TMDB's 6-month cache window), which is exactly why the
    slice size is configurable per type.
    """
    return await _sync_tmdb_type(_series_seed_spec(), slice_size)


# ── TMDB incremental updates (feature 88) ────────────────────────────────────
#
# The seeded catalog is a snapshot.  Left alone it freezes: no release enters,
# and nothing that crosses ``vote_count >= 25`` after the seeding ever gets
# noticed.  Three lanes fix that, and they are separate because they answer
# three different questions with three different sources of truth:
#
# **Lane 1 — new releases (the daily id export).**  TMDB publishes the complete
# list of its ids once a day.  The ids that appear in today's file and were not
# in the one we last processed are the only cheap signal of "new" it offers.
# They are *candidates*, not admissions: see the gate below.
#
# **Lane 2 — promotion (``/discover``).**  Items that were below the threshold
# when the catalog was enumerated and have since crossed it.  Nothing new is
# needed for this — re-running the year enumeration and upserting into
# ``seed_targets`` is exactly what feature 86 already does; the incremental
# just does it on a schedule instead of by hand.  The nightly
# ``_sync_tmdb_type`` then hydrates the new targets like any other.
#
# **Lane 3 — updates (``/changes``).**  The ids TMDB changed in a date window.
# These re-hydrate items the catalog **already holds** and admit nothing: a
# ``/changes`` result carries an id and an ``adult`` flag, so there is nothing
# in it that could justify letting an unknown item in.  This is also what makes
# TMDB's 6-month cache window cheap to honour — the nightly ``last_synced_at``
# rotation stays in place as the safety net for the days ``/changes`` cannot
# reach (its history is 14 days and no more).
#
# **The gate on lane 1 is the load-bearing part.**  A new *id* is not a new
# *item*: TMDB gains roughly a thousand ids a day and most of them are
# catalogue backfill of old, obscure titles — exactly what the ``vote_count``
# threshold exists to keep out.  Since a release has no votes on day one, the
# threshold cannot judge it, so the gate substitutes the checks the detail
# payload *can* answer: a parseable release date inside a window around today,
# no adult/video flag, a status that does not say "this may never exist", and
# a poster or an overview.  ``release_gate_verdict`` in
# ``backlogg.scheduler.discovery`` owns it.  What the gate rejects is not lost:
# lane 2 admits it later if it ever earns an audience.
#
# Each lane is wrapped in its own ``try``.  A failure in one must not abort the
# others (checkpoint C19) — they share nothing but the session factory, and the
# whole point of the watermarks is that an interrupted lane resumes on its own
# without the others waiting for it.

_TMDB_WATERMARK_SOURCE = "TMDB"
_WATERMARK_DAILY_ID_EXPORT = "DAILY_ID_EXPORT"
_WATERMARK_CHANGES = "CHANGES"


@dataclass(frozen=True, slots=True)
class _TmdbIncrementalSpec:
    """Everything that differs between the movie and the series incremental.

    ``seed`` is the feature-86 spec, reused rather than restated: the
    incremental writes through the *same* ``BulkLoadSpec`` and the same batch
    writer as the nightly hydration, which is what makes ``skipped_links``
    accounting, slug realignment and the per-item fallback identical on both
    routes.
    """

    seed: _TmdbSeedSpec
    job_name: str
    export_name: str
    date_key: str
    min_votes: int
    gate: ReleaseGate
    fetch_detail: Callable[[str], Awaitable[dict | None]]
    map_detail: Callable[[dict], tuple[dict, list[BulkPerson]]]
    fetch_changes_page: Callable[..., Awaitable[dict]]
    discover_page: Callable[..., Awaitable[dict]]

    @property
    def item_type(self) -> str:
        return self.seed.item_type


def _release_gate(date_key: str, rejected_statuses: frozenset[str]) -> ReleaseGate:
    """Build the gate from the current settings (read at call time, not import)."""
    return ReleaseGate(
        date_key=date_key,
        max_age_days=max(0, settings.TMDB_INCREMENTAL_MAX_AGE_DAYS),
        horizon_days=max(0, settings.TMDB_INCREMENTAL_HORIZON_DAYS),
        rejected_statuses=rejected_statuses,
    )


# A movie that is ``Rumored`` or ``Canceled`` has nothing to watch: the first
# may never be made, the second was not.  Series are deliberately *not* gated
# on status — a series marked ``Canceled`` is normally one that aired and was
# then dropped, which is a legitimate catalog item, so the same word means
# something different on the two endpoints.
_MOVIE_REJECTED_STATUSES = frozenset({"Rumored", "Canceled"})
_SERIES_REJECTED_STATUSES: frozenset[str] = frozenset()


def _movie_incremental_spec() -> _TmdbIncrementalSpec:
    return _TmdbIncrementalSpec(
        seed=_movie_seed_spec(),
        job_name="incremental_movies",
        export_name=EXPORT_MOVIES,
        date_key="release_date",
        min_votes=settings.TMDB_SEED_MIN_VOTES_MOVIES,
        gate=_release_gate("release_date", _MOVIE_REJECTED_STATUSES),
        fetch_detail=_fetch_movie_detail,
        map_detail=_map_movie_detail,
        fetch_changes_page=_tmdb_movies.get_movie_changes_page,
        discover_page=_tmdb_movies.discover_movies_page,
    )


def _series_incremental_spec() -> _TmdbIncrementalSpec:
    return _TmdbIncrementalSpec(
        seed=_series_seed_spec(),
        job_name="incremental_series",
        export_name=EXPORT_SERIES,
        date_key="first_air_date",
        min_votes=settings.TMDB_SEED_MIN_VOTES_SERIES,
        gate=_release_gate("first_air_date", _SERIES_REJECTED_STATUSES),
        fetch_detail=_fetch_series_detail,
        map_detail=_map_series_detail,
        fetch_changes_page=_tmdb_series.get_series_changes_page,
        discover_page=_tmdb_series.discover_series_page,
    )


@dataclass(slots=True)
class _HydrationOutcome:
    """What one pass of fetch-gate-write did, in numbers an operator can read."""

    considered: int = 0
    written: int = 0
    gated_out: int = 0
    gone: int = 0
    fetch_errors: int = 0
    write_errors: int = 0
    people_errors: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


async def _fetch_detail_guarded(
    sem: asyncio.Semaphore, spec: _TmdbIncrementalSpec, external_id: str
) -> dict | None:
    """Fetch one raw detail under *sem*; exceptions propagate to ``gather``."""
    async with sem:
        return await spec.fetch_detail(external_id)


async def _hydrate_ids(
    spec: _TmdbIncrementalSpec,
    external_ids: list[str],
    *,
    job_name: str,
    gate: ReleaseGate | None = None,
    today: date | None = None,
) -> _HydrationOutcome:
    """Fetch, optionally gate, and write a list of TMDB ids.

    Same shape as the nightly hydration — parallel fetch under
    ``TMDB_SEED_CONCURRENCY``, sequential write through ``BatchWriter`` — and
    for the same reason: ``AsyncSession`` is not safe for concurrent use, and
    going through the batch writer is what makes this route inherit the
    per-item fallback and the ``skipped_links`` accounting instead of growing a
    second, untested copy of them.

    ``gate`` is passed by lane 1 and left out by lane 3: an item the catalog
    already holds has passed the gate at some point and must not be re-judged
    by it (an old film re-hydrated after a change would fail ``too_old`` and
    would then be, absurdly, *not written* — the gate decides admissions, not
    refreshes).
    """
    outcome = _HydrationOutcome(considered=len(external_ids))
    if not external_ids:
        return outcome

    sem = asyncio.Semaphore(max(1, settings.TMDB_SEED_CONCURRENCY))
    chunk_size = max(1, settings.BULK_LOAD_BATCH_SIZE)

    async with async_session_factory() as session:
        writer = BatchWriter(session, spec.seed.bulk_spec, job_name)
        for chunk_start in range(0, len(external_ids), chunk_size):
            chunk = external_ids[chunk_start : chunk_start + chunk_size]
            fetched = await asyncio.gather(
                *(_fetch_detail_guarded(sem, spec, external_id) for external_id in chunk),
                return_exceptions=True,
            )
            for external_id, detail in zip(chunk, fetched, strict=True):
                if isinstance(detail, BaseException):
                    logger.warning(
                        "%s: fetch failed for external_id=%s (%s) — will retry next run",
                        job_name,
                        external_id,
                        detail,
                    )
                    outcome.fetch_errors += 1
                    continue
                if detail is None:
                    # 404: the id was in the feed and is gone from the API
                    # already (deleted or merged). Nothing to write.
                    outcome.gone += 1
                    continue
                if gate is not None:
                    reason = release_gate_verdict(detail, gate=gate, today=today or date.today())
                    if reason is not None:
                        outcome.gated_out += 1
                        outcome.reasons[reason] = outcome.reasons.get(reason, 0) + 1
                        continue
                data, people = spec.map_detail(detail)
                await writer.add(BulkItem(data=data, external_id=external_id, people=people))
            await writer.flush()

    outcome.written = writer.synced
    outcome.write_errors = writer.errors
    outcome.people_errors = writer.people_errors
    return outcome


def _watermark_date(watermark: Watermark | None) -> date | None:
    """Parse a watermark cursor into a date, or None if absent/unreadable.

    An unreadable cursor is treated as "never ran" rather than raised on: the
    recovery from a corrupt cursor is to re-baseline, which is exactly what the
    cold-start branch does, and crashing the lane would leave it corrupt
    forever.
    """
    if watermark is None or not watermark.cursor_value:
        return None
    try:
        return date.fromisoformat(watermark.cursor_value)
    except ValueError:
        logger.warning(
            "%s/%s/%s: unreadable watermark cursor %r — treating it as a cold start",
            watermark.source,
            watermark.kind,
            watermark.item_type,
            watermark.cursor_value,
        )
        return None


async def _read_watermark_date(item_type: str, kind: str) -> date | None:
    """Read one watermark and parse its cursor as a date."""
    async with async_session_factory() as session:
        watermark = await get_sync_watermark(session, _TMDB_WATERMARK_SOURCE, kind, item_type)
    return _watermark_date(watermark)


async def _advance_watermark(item_type: str, kind: str, cursor: date) -> None:
    """Persist ``cursor`` as the last covered point of one mechanism."""
    async with async_session_factory() as session:
        await set_sync_watermark(
            session,
            _TMDB_WATERMARK_SOURCE,
            kind,
            item_type,
            cursor_value=cursor.isoformat(),
        )
        await session.commit()


# ── Lane 1: new releases from the daily id export ────────────────────────────


async def _incremental_new_releases(spec: _TmdbIncrementalSpec, *, now: datetime) -> dict:
    """Admit the releases that appeared in today's id export.

    The diff has two sides and both are subtractions, in this order:

    1. today's export **minus** the export we last processed — the ids that
       *appeared*;
    2. minus everything already known locally (``external_ids`` plus
       ``seed_targets``) — an id already catalogued, queued or retired is not
       new work.

    What happens when the baseline is unusable — never set (first run), older
    than ``TMDB_INCREMENTAL_MAX_EXPORT_GAP_DAYS``, or no longer downloadable
    (TMDB keeps three months) — is a **re-baseline**: today's file becomes the
    new baseline, nothing is admitted this run, and the skipped stretch is
    reported in the result and in a warning.  It is not silent and it is not
    lost either: an item that appeared during that stretch and matters will
    cross the vote threshold and enter through lane 2.  The alternative —
    diffing against a baseline months old — would put hundreds of thousands of
    ids through the detail endpoint to admit a handful.
    """
    today = now.astimezone(UTC).date()
    export_day = latest_export_date(now)
    result: dict = {
        "export_day": export_day.isoformat(),
        "baseline_day": None,
        "rebaselined": False,
        "rebaseline_reason": None,
        "skipped_days": 0,
        "appeared": 0,
        "admitted": 0,
        "gated_out": 0,
        "gate_reasons": {},
        "gone": 0,
        "errors": 0,
        "people_errors": 0,
        "watermark_advanced": False,
    }

    baseline_day = await _read_watermark_date(spec.item_type, _WATERMARK_DAILY_ID_EXPORT)
    result["baseline_day"] = baseline_day.isoformat() if baseline_day else None

    async def rebaseline(reason: str, skipped_days: int = 0) -> dict:
        result["rebaselined"] = True
        result["rebaseline_reason"] = reason
        result["skipped_days"] = skipped_days
        await _advance_watermark(spec.item_type, _WATERMARK_DAILY_ID_EXPORT, export_day)
        result["watermark_advanced"] = True
        return result

    if baseline_day is None:
        logger.info(
            "%s: no daily-export watermark yet — recording %s as the baseline; the "
            "first diff runs tomorrow",
            spec.job_name,
            export_day.isoformat(),
        )
        return await rebaseline("cold_start")

    if baseline_day >= export_day:
        # Already processed the newest published file (a second run the same
        # day, or a run before ~08:00 UTC). Refresh last_run_at so the freshness
        # signal is honest, and do nothing else.
        logger.info(
            "%s: export %s already processed — nothing appeared since",
            spec.job_name,
            baseline_day.isoformat(),
        )
        await _advance_watermark(spec.item_type, _WATERMARK_DAILY_ID_EXPORT, baseline_day)
        return result

    gap_days = (export_day - baseline_day).days
    if gap_days > max(1, settings.TMDB_INCREMENTAL_MAX_EXPORT_GAP_DAYS):
        logger.warning(
            "%s: last processed export is %s, %d days behind %s (limit %d) — "
            "re-baselining on today's file instead of diffing that far back; "
            "releases from that stretch will enter through the promotion sweep "
            "once they cross the vote threshold",
            spec.job_name,
            baseline_day.isoformat(),
            gap_days,
            export_day.isoformat(),
            max(1, settings.TMDB_INCREMENTAL_MAX_EXPORT_GAP_DAYS),
        )
        return await rebaseline("gap_too_large", gap_days)

    try:
        baseline_ids = await asyncio.to_thread(load_export_ids, spec.export_name, baseline_day)
    except ExportUnavailable:
        logger.warning(
            "%s: the export of %s is no longer published (TMDB keeps three months) — "
            "re-baselining on %s; the %d skipped day(s) are only recoverable through "
            "the promotion sweep",
            spec.job_name,
            baseline_day.isoformat(),
            export_day.isoformat(),
            gap_days,
        )
        return await rebaseline("baseline_unavailable", gap_days)

    async with async_session_factory() as session:
        known_ids = await get_known_source_ids(
            session, spec.item_type, SEED_TARGET_SOURCES[spec.item_type]
        )

    appeared = await asyncio.to_thread(
        collect_appeared_entries,
        spec.export_name,
        export_day,
        baseline_ids=baseline_ids,
        known_ids=known_ids,
    )
    result["appeared"] = len(appeared)
    logger.info(
        "%s: %d id(s) appeared between the %s and %s exports (%d known locally already)",
        spec.job_name,
        len(appeared),
        baseline_day.isoformat(),
        export_day.isoformat(),
        len(known_ids),
    )

    outcome = await _hydrate_ids(
        spec,
        [entry.external_id for entry in appeared],
        job_name=spec.job_name,
        gate=spec.gate,
        today=today,
    )
    result["admitted"] = outcome.written
    result["gated_out"] = outcome.gated_out
    result["gate_reasons"] = dict(sorted(outcome.reasons.items()))
    result["gone"] = outcome.gone
    result["errors"] = outcome.fetch_errors + outcome.write_errors
    result["people_errors"] = outcome.people_errors
    logger.info(
        "%s: admitted %d of %d appeared id(s); %d rejected by the release gate (%s), "
        "%d gone, %d fetch error(s), %d write error(s)",
        spec.job_name,
        outcome.written,
        len(appeared),
        outcome.gated_out,
        result["gate_reasons"] or "-",
        outcome.gone,
        outcome.fetch_errors,
        outcome.write_errors,
    )

    if outcome.fetch_errors:
        # The stretch was *not* covered: some ids never got an answer. Leaving
        # the watermark where it is re-diffs the same pair of files next run,
        # and the ids admitted in the meantime drop out of it by themselves
        # (they are locally known now), so the retry is cheap and converges.
        #
        # Write errors deliberately do NOT hold the watermark back: a row the
        # writer rejects is rejected deterministically, so blocking on it would
        # stall this lane for ever on a payload that will never change.
        logger.warning(
            "%s: %d fetch error(s) — keeping the daily-export watermark at %s so the "
            "diff is retried next run",
            spec.job_name,
            outcome.fetch_errors,
            baseline_day.isoformat(),
        )
        return result

    await _advance_watermark(spec.item_type, _WATERMARK_DAILY_ID_EXPORT, export_day)
    result["watermark_advanced"] = True
    return result


# ── Lane 2: the promotion sweep ──────────────────────────────────────────────


async def _persist_promotion_targets(item_type: str, targets: list[DiscoveredTarget]) -> None:
    """Sink for the promotion enumeration: upsert one page and commit.

    Per page rather than at the end so an interrupted sweep keeps what it had
    already enumerated — the same reason ``scripts/seed_tmdb_targets.py``
    commits per page.

    Shared by **both** promotion sweeps since issue #34: the source is looked up
    in ``SEED_TARGET_SOURCES`` rather than passed in, so ``MOVIE``/``SERIES``
    land on TMDB and ``GAME`` on IGDB with no branch here.  The two enumerations
    differ in how they walk (year windows against a keyset cursor) and in
    nothing at all in where the answer goes, so this stays one function.
    """
    rows = [
        SeedTargetRow(
            item_type=item_type,
            source=SEED_TARGET_SOURCES[item_type],
            external_id=target.external_id,
            vote_count=target.vote_count,
            release_year=target.release_year,
        )
        for target in targets
    ]
    async with async_session_factory() as session:
        await upsert_seed_targets(session, rows)
        await session.commit()


async def _incremental_promotion(spec: _TmdbIncrementalSpec, *, now: datetime) -> dict:
    """Re-enumerate recent years so items that crossed the threshold enter.

    This lane deliberately writes **no catalog rows**.  It re-runs the feature
    86 enumeration over the last ``TMDB_PROMOTION_YEARS`` release years and
    upserts what it finds into ``seed_targets``; anything that was not already
    linked becomes pending work and the nightly ``_sync_tmdb_type`` hydrates it
    with no further intervention.  Re-enumerating is idempotent — an existing
    target keeps its attempts and its ``discovered_at`` — so running this every
    night costs the requests and nothing else.

    It carries no watermark, and that is not an omission: the sweep has no
    "since".  It asks a question about the present state of ``/discover``
    (which ids clear the threshold today) whose answer does not depend on when
    it was last asked, so there is nothing to resume.
    """
    end_year = settings.TMDB_SEED_END_YEAR or now.astimezone(UTC).year + 1
    span = max(1, settings.TMDB_PROMOTION_YEARS)
    start_year = max(settings.TMDB_SEED_START_YEAR, end_year - span + 1)
    logger.info(
        "%s: promotion sweep over %d-%d with vote_count>=%d",
        spec.job_name,
        start_year,
        end_year,
        spec.min_votes,
    )

    stats = await enumerate_windows(
        year_windows(start_year, end_year),
        fetch_page=partial(spec.discover_page, min_votes=spec.min_votes),
        date_key=spec.date_key,
        on_targets=partial(_persist_promotion_targets, spec.item_type),
        concurrency=settings.TMDB_SEED_CONCURRENCY,
    )

    async with async_session_factory() as session:
        progress = await count_seed_target_progress(
            session,
            spec.item_type,
            SEED_TARGET_SOURCES[spec.item_type],
            max(1, settings.TMDB_SEED_MAX_ATTEMPTS),
        )
    logger.info(
        "%s: promotion sweep enumerated %d target(s) over %d window(s); %d pending "
        "hydration afterwards",
        spec.job_name,
        stats.targets,
        stats.windows,
        progress.pending,
    )
    return {
        "start_year": start_year,
        "end_year": end_year,
        "windows": stats.windows,
        "enumerated": stats.targets,
        "truncated_windows": stats.truncated_windows,
        "pending_after": progress.pending,
    }


# ── Lane 3: updates from /changes ────────────────────────────────────────────


async def _incremental_changes(spec: _TmdbIncrementalSpec, *, now: datetime) -> dict:
    """Re-hydrate the catalog items TMDB reports as changed.

    The window comes from ``plan_change_windows``: the watermark says which day
    was last covered — that exact value is what ``since`` means there, no
    off-by-one adjustment in between — the plan slices the range into requests
    of at most 14 days and reports the stretch TMDB no longer keeps as
    *uncovered* instead of pretending to have refreshed it.  That stretch is
    the nightly ``last_synced_at`` rotation's job, which is why feature 88
    keeps it.  The watermark day itself is re-requested on purpose (a run at
    09:00 cannot have seen that day's afternoon changes) and is *not* counted
    as uncovered.

    The watermark is advanced **per window, only after the window is fully
    processed**.  A window that fails stops the lane there and leaves the
    watermark at the end of the previous one, so "the watermark moved" keeps
    meaning "that range was covered" rather than "we tried".

    A window is not always covered whole, either: ``/changes`` enforces the
    same 500-page cap as ``/discover`` (~73 pages a day in movies), so
    :func:`fetch_change_ids` splits an oversized window down to single days
    and, if a single day still overflows, walks its first 500 pages and
    reports it as **not covered**.  This lane then advances the watermark only
    up to ``ChangeFeed.covered_through`` and stops: the days after the hole
    would be re-requested next run anyway — the mark cannot pass it — so
    walking them now would buy freshness the nightly sweep already provides at
    twice the request cost.

    Ids that are not in the catalog are dropped, counted, and not admitted:
    ``/changes`` says nothing about quality, so admitting from it would be a
    gate that lets everything through.
    """
    today = now.astimezone(UTC).date()
    since = await _read_watermark_date(spec.item_type, _WATERMARK_CHANGES)
    plan = plan_change_windows(since=since, until=today, context=f"{spec.job_name} /changes")

    result: dict = {
        "since": since.isoformat() if since else None,
        "until": today.isoformat(),
        "windows_planned": len(plan.windows),
        "windows_covered": 0,
        "uncovered_days": plan.uncovered_days,
        "truncated_windows": 0,
        "truncated_labels": [],
        "changed_ids": 0,
        "in_catalog": 0,
        "refreshed": 0,
        "gone": 0,
        "errors": 0,
        "people_errors": 0,
        "covered_through": None,
    }

    covered_through: date | None = None
    for window in plan.windows:
        try:
            feed = await fetch_change_ids(
                window,
                fetch_page=spec.fetch_changes_page,
                concurrency=settings.TMDB_SEED_CONCURRENCY,
            )
        except Exception:
            logger.exception(
                "%s: /changes window %s failed — stopping the lane here, the watermark stays at %s",
                spec.job_name,
                window.label,
                covered_through.isoformat() if covered_through else (since or "unset"),
            )
            result["errors"] += 1
            break

        changed = feed.ids
        result["truncated_windows"] += feed.truncated_windows
        result["truncated_labels"].extend(feed.truncated_labels)

        async with async_session_factory() as session:
            in_catalog = await filter_catalogued_external_ids(
                session, spec.item_type, SEED_TARGET_SOURCES[spec.item_type], changed
            )
        # Keep the feed's order so the run is deterministic and reproducible.
        to_refresh = [external_id for external_id in changed if external_id in in_catalog]
        result["changed_ids"] += len(changed)
        result["in_catalog"] += len(to_refresh)
        logger.info(
            "%s: /changes %s reported %d changed id(s) over %d sub-window(s), "
            "%d of them in the catalog",
            spec.job_name,
            window.label,
            len(changed),
            feed.windows,
            len(to_refresh),
        )

        outcome = await _hydrate_ids(spec, to_refresh, job_name=spec.job_name)
        result["refreshed"] += outcome.written
        result["gone"] += outcome.gone
        result["errors"] += outcome.fetch_errors + outcome.write_errors
        result["people_errors"] += outcome.people_errors

        if outcome.fetch_errors:
            logger.warning(
                "%s: %d item(s) of window %s could not be fetched — not marking the "
                "window as covered",
                spec.job_name,
                outcome.fetch_errors,
                window.label,
            )
            break

        if feed.covered_through is None:
            # The window's first day saturated: not one day of it is covered,
            # so the watermark stays exactly where it was.
            logger.warning(
                "%s: /changes window %s saturated the %d-page cap on its first day "
                "(%s) — the watermark stays at %s and those days are left to the "
                "nightly last_synced_at sweep",
                spec.job_name,
                window.label,
                MAX_DISCOVER_PAGES,
                ", ".join(feed.truncated_labels),
                covered_through.isoformat() if covered_through else (since or "unset"),
            )
            break

        covered_through = feed.covered_through
        await _advance_watermark(spec.item_type, _WATERMARK_CHANGES, covered_through)
        if feed.covered_through < window.end:
            logger.warning(
                "%s: /changes window %s is only covered through %s — day(s) %s "
                "saturated the %d-page cap; stopping the lane there so the "
                "watermark never passes an uncovered stretch",
                spec.job_name,
                window.label,
                covered_through.isoformat(),
                ", ".join(feed.truncated_labels),
                MAX_DISCOVER_PAGES,
            )
            break
        result["windows_covered"] += 1

    result["covered_through"] = covered_through.isoformat() if covered_through else None
    return result


# ── The job itself ───────────────────────────────────────────────────────────


async def _sync_tmdb_incremental(spec: _TmdbIncrementalSpec) -> dict:
    """Run the three incremental lanes for one TMDB content type.

    Every lane is isolated: an exception inside one is logged, counted in
    ``errors`` and does not stop the other two (checkpoint C19).  The three
    are sequential rather than concurrent on purpose — they all talk to TMDB
    under the same rate budget, and running them in parallel would triple the
    in-flight request count that ``TMDB_SEED_CONCURRENCY`` is calibrated for.

    ``skipped_links`` is collected across the whole job through the shared
    ``collect_link_skips()`` accumulator, exactly like the nightly slice: both
    write paths feed it, so a link this run wanted and could not have is
    visible here too instead of only in the nightly numbers.
    """
    logger.info("%s: starting", spec.job_name)
    get_metrics().inc_counter("backlogg_syncs_total", labels={"type": spec.seed.metric_label})
    start = time.monotonic()
    now = datetime.now(UTC)

    lanes: dict[str, Callable[[], Awaitable[dict]]] = {
        "new_releases": partial(_incremental_new_releases, spec, now=now),
        "promotion": partial(_incremental_promotion, spec, now=now),
        "changes": partial(_incremental_changes, spec, now=now),
    }
    results: dict[str, dict] = {}
    lane_errors = 0

    with collect_link_skips() as link_skips:
        for name, lane in lanes.items():
            try:
                results[name] = await lane()
            except Exception:
                logger.exception(
                    "%s: lane %s failed — the other lanes continue", spec.job_name, name
                )
                results[name] = {"failed": True}
                lane_errors += 1

    errors = lane_errors + sum(int(lane.get("errors", 0)) for lane in results.values())
    people_errors = sum(int(lane.get("people_errors", 0)) for lane in results.values())
    synced = int(results.get("new_releases", {}).get("admitted", 0)) + int(
        results.get("changes", {}).get("refreshed", 0)
    )
    summary = {
        "item_type": spec.item_type,
        "synced": synced,
        "errors": errors,
        "people_errors": people_errors,
        "skipped_links": link_skips.count,
        "duration_s": round(time.monotonic() - start, 1),
        "new_releases": results["new_releases"],
        "promotion": results["promotion"],
        "changes": results["changes"],
    }
    logger.info(
        "%s: done — %d item(s) written, %d error(s), %d people_errors, %d skipped_links in %.1fs",
        spec.job_name,
        synced,
        errors,
        people_errors,
        link_skips.count,
        summary["duration_s"],
    )
    return summary


async def sync_movies_incremental() -> dict:
    """Run the movie incremental: new releases, promotion and /changes.

    Not part of the nightly slice and not exposed over HTTP: the daily id
    export is 28 MB and Render's free tier both sleeps and caps a request at
    ~15 min, so this runs on GitHub Actions straight against Neon like the
    other bulk paths (features 86 and 87): ``scripts/incremental_sync.py``,
    scheduled by ``.github/workflows/incremental-sync.yml``.
    """
    return await _sync_tmdb_incremental(_movie_incremental_spec())


async def sync_series_incremental() -> dict:
    """Run the series incremental — same three lanes as ``sync_movies_incremental``.

    The series numbers are an order of magnitude smaller (the ``tv_series_ids``
    export is 5 MB against 28, and the catalog holds 10.880 series against
    57.135 movies), so the same code is comfortably cheaper here.
    """
    return await _sync_tmdb_incremental(_series_incremental_spec())


# ── Cursor job: books ────────────────────────────────────────────────────────
#
# The last job on the offset walk.  Open Library's seed query is already a
# *filtered* search (feature 73's notoriety thresholds) rather than a raw
# popularity ranking, so it never suffered the reordering that forced movies
# and series off ``/popular`` — but it does suffer the other defect:
# ``SEED_TOP_N_BOOKS`` is the wraparound target, production has it at 10.000,
# and the filter selects 18.874 works, so the cursor turns around before
# covering the catalog.  That is issue #27, it is still **open**, and feature
# 90 does not touch it: converting games changes nothing about the book walk.
# The seeding of books does not go through here at all since feature 87 (it is
# ``scripts/seed_openlibrary_books.py``, from the monthly dumps).


async def sync_books(slice_size: int | None = None) -> dict:
    """Fetch a slice of popular books from Open Library and upsert them locally.

    ``slice_size`` overrides ``settings.SYNC_SLICE_SIZE_BOOKS`` (which itself
    overrides the global ``settings.SYNC_SLICE_SIZE``) when provided.
    Returns a dict with keys ``synced``, ``errors``, ``people_errors``,
    ``skipped_links``, ``offset`` and ``duration_s``.
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
            "skipped_links": 0,
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
            "skipped_links": 0,
            "offset": offset,
            "duration_s": round(time.monotonic() - start, 1),
        }

    with collect_link_skips() as link_skips:
        async with async_session_factory() as session:
            writer = BatchWriter(session, books_repo.BOOK_BULK_SPEC, "sync_books")
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
                        logger.exception(
                            "sync_books: failed to fetch authors for work_id=%s", work_id
                        )
                        people_errors += 1

                await writer.add(BulkItem(data=book_data, external_id=work_id, people=people))
            await writer.flush()

            await _persist_cursor(
                session,
                "BOOK",
                _next_offset(offset, len(raw_list), slice_size, target),
                "sync_books",
            )

    synced = writer.synced
    errors += writer.errors
    people_errors += writer.people_errors
    skipped_links = link_skips.count
    logger.info(
        "sync_books: done — %d items upserted, %d errors, %d people_errors, "
        "%d skipped_links (offset %d)",
        synced,
        errors,
        people_errors,
        skipped_links,
        offset,
    )
    return {
        "synced": synced,
        "errors": errors,
        "people_errors": people_errors,
        "skipped_links": skipped_links,
        "offset": offset,
        "duration_s": round(time.monotonic() - start, 1),
    }


# ── IGDB job: target-driven hydration (feature 90) ───────────────────────────
#
# ``sync_games`` used to walk IGDB's ``rating_count`` ranking by offset and
# wrap around at ``SEED_TOP_N_GAMES``.  That is gone.  Games were the last type
# still seeded by a cursor and it cost three concrete things
# (``backend_feature_list.json`` #90):
#
# 1. **A catalog capped at 10.000** over the ~31.988 games that pass the
#    quality filter — the seeding of 2026-09-07 left exactly 10.000 rows in
#    ``games``, which is the wraparound target and not a product decision.
# 2. **An operational trap**: the backfill dispatch needed ``-f
#    seed_top_n=10000`` and it had to *match* the Render variable, because both
#    wrote the same ``sync_cursors`` row.  No other type had that.
# 3. **Four ways of seeding** where two are enough.
#
# The replacement is the mechanism of feature 86, unchanged in shape: the
# catalog is enumerated into ``seed_targets`` (``scripts/seed_igdb_targets.py``,
# keyset over ``game_type`` allowlist + ``rating > 0``) and each slice hydrates
# the **difference** against ``external_ids``, topped up by the
# ``last_synced_at`` rotation once nothing is pending.  Retirement
# (``attempts``/``unreachable_at``) and the ``skipped_links`` accounting are
# the *same* code as movies and series — ``_read_seed_work_list``,
# ``_stamp_seed_outcomes``, ``_recount_seed_progress``, ``_seed_result``,
# ``collect_link_skips`` — not a second copy of it.
#
# What is **not** shared is the fetch, and that is why this is a sibling of
# ``_sync_tmdb_type`` rather than a fifth ``_TmdbSeedSpec``.  TMDB has no bulk
# detail endpoint: it pays one HTTP request per item, so its engine is built
# around ``asyncio.gather`` under a semaphore and a per-item 404.  IGDB answers
# ``where id = (...)`` with up to 500 fully-hydrated games in **one** request,
# so the loop here is one request per chunk and "gone" is an id missing from
# the answer.  Generalising the TMDB engine to cover both would have meant
# reshaping the per-item fetch path that has been running in production since
# feature 86 to serve a case it does not have — a bad trade against the one
# rule that matters here: do not break what works.
#
# The ``sync_cursors`` row for GAME stops being read and written, exactly like
# the MOVIE and SERIES rows did in feature 86.  It is left in the table rather
# than deleted (see the ``SyncCursor`` model docstring): a stale row costs
# nothing and deleting rows nobody reads is a migration with no upside.


async def sync_games(slice_size: int | None = None) -> dict:
    """Hydrate a slice of the enumerated game catalog from IGDB.

    Work list: the game targets in ``seed_targets`` that the catalog does not
    have yet (the ``game_type`` allowlist plus ``rating > 0`` decides which
    games are targets at all — see ``scripts/seed_igdb_targets.py``), topped up
    by the least recently synced games once none are pending.  ``slice_size``
    overrides ``settings.SYNC_SLICE_SIZE_GAMES`` (which itself overrides the
    global ``settings.SYNC_SLICE_SIZE``).

    The ``game_type`` allowlist is re-checked on every payload before it is
    written, not only when the target was enumerated: see the gate inside the
    loop.  It is reported in the log rather than in the result dict — the keys
    below are a contract shared with ``_sync_tmdb_type``, ``SyncResponse`` and
    ``scripts/backfill_sync.py``, and a games-only counter has no place in it.

    Returns a dict with ``synced``, ``errors``, ``skipped_links``, ``offset``
    (always 0 — no cursor), ``duration_s``, ``pending`` (workable targets
    left), ``stuck`` (targets retired as unreachable/unlinkable) and
    ``refreshed``.  ``people_errors`` is always 0 and present only because the
    key is part of the shared result contract: games carry no people credits,
    only company credits that travel inside the payload.
    """
    logger.info("sync_games: starting")
    get_metrics().inc_counter("backlogg_syncs_total", labels={"type": "game"})
    start = time.monotonic()
    source = SEED_TARGET_SOURCES["GAME"]
    size = max(1, _resolve_slice_size("GAME", slice_size))

    try:
        pending, refresh, progress = await _read_seed_work_list("GAME", source, size)
    except Exception:
        logger.exception("sync_games: failed to read the seed work list")
        return _seed_failure_result(start)

    work = pending + refresh
    logger.info(
        "sync_games: %d workable target(s) pending (%d gone from IGDB, %d unlinkable) — this "
        "slice takes %d of them plus %d refresh item(s) by oldest last_synced_at",
        progress.pending,
        progress.gone,
        progress.unlinkable,
        len(pending),
        len(refresh),
    )
    if not work:
        logger.info("sync_games: nothing to do — no pending targets and an empty catalog")
        return _seed_result(
            start,
            synced=0,
            errors=0,
            people_errors=0,
            skipped_links=0,
            progress=progress,
            refreshed=0,
        )

    errors = 0
    # Same split as the TMDB engine: only *conclusive* outcomes are booked.
    # A request that raised belongs to neither list and is retried next run
    # without spending any of its targets' budget.
    resolved: list[str] = []
    gone: list[str] = []
    pending_targets = set(pending)
    # Targets refused by the ``game_type`` allowlist on arrival, and catalog
    # items IGDB has reclassified out of it since they were written.
    gated_out = 0
    reclassified = 0

    with collect_link_skips() as link_skips:
        async with async_session_factory() as session:
            writer = BatchWriter(session, games_repo.GAME_BULK_SPEC, "sync_games")
            for chunk_start in range(0, len(work), IGDB_PAGE_SIZE):
                chunk = work[chunk_start : chunk_start + IGDB_PAGE_SIZE]
                try:
                    raw_list = await _igdb_client.get_games_by_ids(chunk)
                except Exception:
                    # One error for the request, not one per id: the chunk is
                    # the unit of work that failed. The ids keep their attempt
                    # counters untouched and come back next run.
                    logger.exception(
                        "sync_games: failed to fetch %d id(s) from IGDB — not counted as "
                        "attempts, will retry next run",
                        len(chunk),
                    )
                    errors += 1
                    continue

                returned: set[str] = set()
                for raw in raw_list:
                    igdb_id = raw.get("id")
                    if not igdb_id:
                        continue
                    external_id = str(igdb_id)
                    returned.add(external_id)
                    try:
                        game_data = _igdb_client.game_to_dict(raw)
                    except Exception:
                        logger.exception("sync_games: error mapping igdb_id=%s", igdb_id)
                        errors += 1
                        continue
                    # The allowlist gate, re-applied on the payload.  The
                    # hydration query carries no ``game_type`` clause on
                    # purpose (see ``get_games_by_ids``), so the enumeration's
                    # verdict can be stale by the time an id is hydrated: a
                    # target enumerated as MAIN_GAME and reclassified to BUNDLE
                    # in between would otherwise walk straight into the catalog
                    # past issue #14.  Checked on the *mapped* value, not on
                    # the raw field, so the gate cannot disagree with what the
                    # row would actually store.
                    if game_data["game_type"] not in ALLOWED_GAME_TYPES:
                        if external_id in pending_targets:
                            # Never in the catalog and no longer wanted in it:
                            # do not write, and book the pass as conclusive so
                            # the target spends its attempts and retires as
                            # unlinkable instead of costing a slice slot every
                            # night for ever.  Attempts rather than immediate
                            # retirement because a reclassification can be
                            # undone, and a target that becomes eligible again
                            # within its budget then links with no operator.
                            gated_out += 1
                            resolved.append(external_id)
                            logger.info(
                                "sync_games: external_id=%s is %s, outside the allowlist — not "
                                "written (issue #14)",
                                external_id,
                                game_data["game_type"],
                            )
                            continue
                        # Already in the catalog: this is the refresh rotation,
                        # and refreshing is not the place to evict.  Users have
                        # library entries, ratings and reviews pointing at the
                        # row, so dropping it here would delete their data as a
                        # side effect of a nightly refresh, and skipping the
                        # write would only freeze it on a stale payload.  It is
                        # written like any other refresh and logged loudly, so
                        # a reclassified catalog item is visible to the
                        # operator instead of silent.
                        reclassified += 1
                        logger.warning(
                            "sync_games: external_id=%s is in the catalog but IGDB now "
                            "classifies it as %s, outside the allowlist (issue #14) — refreshed, "
                            "not removed",
                            external_id,
                            game_data["game_type"],
                        )
                    if external_id in pending_targets:
                        resolved.append(external_id)
                    # Games carry no people: developers/publishers are company
                    # credits and travel inside ``game_data`` itself.
                    await writer.add(BulkItem(data=game_data, external_id=external_id))

                # An id IGDB did not answer for is this source's 404: it was
                # enumerated but the record is gone (deleted or merged). A
                # definitive answer, so the target retires now instead of
                # costing a slot on every future run.
                for external_id in chunk:
                    if external_id in returned:
                        continue
                    logger.info(
                        "sync_games: external_id=%s is gone from IGDB — retiring the target",
                        external_id,
                    )
                    if external_id in pending_targets:
                        gone.append(external_id)
            await writer.flush()

            await _stamp_seed_outcomes(session, "GAME", source, resolved, gone, "sync_games")
            after = await _recount_seed_progress(session, "GAME", source, progress, "sync_games")

    synced = writer.synced
    errors += writer.errors
    skipped_links = link_skips.count
    logger.info(
        "sync_games: done — %d items upserted, %d errors, %d skipped_links, %d gone from "
        "IGDB (%d targets still pending, %d stuck: %d gone, %d unlinkable)",
        synced,
        errors,
        skipped_links,
        len(gone),
        after.pending,
        after.stuck,
        after.gone,
        after.unlinkable,
    )
    if after.unlinkable:
        logger.warning(
            "sync_games: %d target(s) retired as unlinkable after %d conclusive passes — they "
            "resolve at IGDB but never get an external_ids row (a target IGDB has reclassified "
            "out of the game_type allowlist retires this way)",
            after.unlinkable,
            _seed_max_attempts(),
        )
    if gated_out or reclassified:
        logger.warning(
            "sync_games: game_type allowlist — %d target(s) refused on arrival (not written), "
            "%d catalog item(s) reclassified out of it (refreshed, not removed)",
            gated_out,
            reclassified,
        )
    return _seed_result(
        start,
        synced=synced,
        errors=errors,
        people_errors=0,
        skipped_links=skipped_links,
        progress=after,
        refreshed=len(refresh),
    )


# ── IGDB incremental updates (feature 88) ────────────────────────────────────
#
# IGDB is the cheapest of the three sources to keep fresh, because its query
# language answers both questions directly: every record carries ``created_at``
# and ``updated_at``, so there is no export file to diff and no changes
# endpoint to page through.  Three lanes, of which the first two carry **two
# independent watermarks**:
#
# * ``CREATED_AT`` — games added to IGDB since the last run.  This is the only
#   lane that admits new rows, and the gate it admits them through is the
#   ``game_type`` allowlist of feature 65 (issue #14): a game does not enter
#   the catalog for being new, it enters for being a game and not a bundle, a
#   mod, a port, a pack or an update.  The allowlist is in the query's
#   ``where`` *and* checked again here on the payload — the clause is a filter
#   applied by a third party, the check is the gate this code owns.
# * ``UPDATED_AT`` — games whose record changed.  Refresh only: an id is
#   re-written only if the catalog already holds it, exactly like the TMDB
#   ``/changes`` lane.
#
# * ``PROMOTION`` — the third lane, and the one that closed **issue #34**.
#   Promotion means "an item that was below the bar has crossed it": for games
#   the bar is ``rating > 0``, which a game crosses with no publication event at
#   all, just by someone rating it, so neither of the lanes above can see it
#   (one only reports what is new to IGDB, the other refuses ids the catalog
#   does not hold).  Feature 88 argued the nightly cursor walk covered that by
#   re-walking IGDB's ranking every night; **that argument expired with the
#   cursor** in feature 90, and what replaced it was a person running
#   ``scripts/seed_igdb_targets.py``.  The mechanism was already the right one —
#   the same as TMDB's: re-enumerate, upsert the newly-qualifying ids as
#   targets, let the nightly slice hydrate them — but the trigger was a human
#   decision, so the promotion delay was however long it took somebody to
#   remember.  Now it is a lane: 64 requests and 52 s per run (measured
#   2026-09-09), idempotent, and it writes no catalog row.  The script stays as
#   the manual and resumable route (``--start-after`` after a stall), not as the
#   only trigger.
#
# The ``CREATED_AT`` lane is untouched by any of that and still closes a hole
# no enumeration can: a game released *today* has no rating, so it cannot be
# enumerated at all until somebody rates it.
#
# Each lane is wrapped in its own ``try``: one failing must not abort the others
# (checkpoint C19), which is the whole reason the two watermarks are separate
# rows instead of one — and the reason the watermark-less promotion sweep can be
# added without putting the other two at risk.

_IGDB_WATERMARK_SOURCE = "IGDB"
_WATERMARK_CREATED_AT = "CREATED_AT"
_WATERMARK_UPDATED_AT = "UPDATED_AT"


def _watermark_instant(watermark: Watermark | None) -> datetime | None:
    """Parse a watermark cursor into an aware instant, or None if unusable.

    Same policy as ``_watermark_date`` on the TMDB side: an unreadable cursor
    is treated as "never ran" and reported, never raised on — the recovery from
    a corrupt cursor is the cold-start branch, and crashing here would leave it
    corrupt for ever.  A cursor that parses but is naive is also rejected: the
    lane would compare it against an aware ``now`` and blow up one line later.
    """
    if watermark is None or not watermark.cursor_value:
        return None
    try:
        parsed = datetime.fromisoformat(watermark.cursor_value)
    except ValueError:
        logger.warning(
            "%s/%s/%s: unreadable watermark cursor %r — treating it as a cold start",
            watermark.source,
            watermark.kind,
            watermark.item_type,
            watermark.cursor_value,
        )
        return None
    if parsed.tzinfo is None:
        logger.warning(
            "%s/%s/%s: naive watermark cursor %r — treating it as a cold start",
            watermark.source,
            watermark.kind,
            watermark.item_type,
            watermark.cursor_value,
        )
        return None
    return parsed


async def _read_game_watermark(kind: str) -> datetime | None:
    """Read one IGDB watermark and parse its cursor as an instant."""
    async with async_session_factory() as session:
        watermark = await get_sync_watermark(session, _IGDB_WATERMARK_SOURCE, kind, "GAME")
    return _watermark_instant(watermark)


async def _advance_game_watermark(kind: str, cursor: datetime) -> None:
    """Persist ``cursor`` as the newest IGDB record this lane has covered."""
    async with async_session_factory() as session:
        await set_sync_watermark(
            session,
            _IGDB_WATERMARK_SOURCE,
            kind,
            "GAME",
            cursor_value=cursor.isoformat(),
        )
        await session.commit()


def _newest_timestamp(raw_list: list[dict], field_name: str) -> datetime | None:
    """The newest ``created_at``/``updated_at`` in a page, as an aware datetime.

    Taken over **every** row the query returned, including the ones this run
    refuses to write: they were inside the window and were answered for, so
    leaving the watermark behind them would make the next run pay for them
    again, for ever.  Epoch seconds are converted explicitly by the adapter
    (checkpoint C14).
    """
    stamps = [
        stamp
        for stamp in (parse_igdb_timestamp(raw.get(field_name)) for raw in raw_list)
        if stamp is not None
    ]
    return max(stamps) if stamps else None


async def _write_games(raw_list: list[dict], job_name: str) -> dict:
    """Map and write a list of raw IGDB games through the shared batch writer.

    Uses the same ``GAME_BULK_SPEC`` and the same ``BatchWriter`` as
    ``sync_games`` — the incremental must not grow a second, untested copy of
    the write path, its slug realignment or its ``skipped_links`` accounting.
    """
    written = 0
    errors = 0
    if not raw_list:
        return {"written": 0, "errors": 0}

    async with async_session_factory() as session:
        writer = BatchWriter(session, games_repo.GAME_BULK_SPEC, job_name)
        for raw in raw_list:
            igdb_id = raw.get("id")
            if not igdb_id:
                continue
            try:
                game_data = _igdb_client.game_to_dict(raw)
            except Exception:
                logger.exception("%s: error mapping igdb_id=%s", job_name, igdb_id)
                errors += 1
                continue
            await writer.add(BulkItem(data=game_data, external_id=str(igdb_id)))
        await writer.flush()

    written = writer.synced
    errors += writer.errors
    return {"written": written, "errors": errors}


async def _incremental_new_games(*, now: datetime) -> dict:
    """Lane 1 — games created in IGDB since the watermark.

    Cold start asks for the last ``IGDB_INCREMENTAL_LOOKBACK_DAYS`` instead of
    for everything: ``created_at > 0`` is IGDB's entire database, and a bounded
    window is both immediately useful and impossible to confuse with a seeding.

    The allowlist check on ``game_type`` is what makes this lane a gate rather
    than a funnel — a game that is a bundle, a mod, a port, a pack or an update
    is counted in ``gated_out`` and never written, exactly as the enumeration
    refuses it: ``IGDB_CATALOG_WHERE`` is ``game_type = (allowlist) & rating >
    0``, so a bundle is not a catalog target no matter how it is discovered.
    (This used to say "as the nightly ranking walk would have refused it";
    feature 90 retired that walk, and the bar it stood for now lives in the
    enumeration.)
    """
    since = await _read_game_watermark(_WATERMARK_CREATED_AT)
    cold_start = since is None
    if since is None:
        since = now - timedelta(days=max(1, settings.IGDB_INCREMENTAL_LOOKBACK_DAYS))

    max_items = max(1, settings.IGDB_INCREMENTAL_MAX_ITEMS)
    raw_list = await _igdb_client.get_games_created_since(since, limit=max_items)

    admitted: list[dict] = []
    gated_out = 0
    gate_reasons: dict[str, int] = {}
    for raw in raw_list:
        game_type = raw.get("game_type")
        if game_type not in ALLOWED_GAME_CATEGORY_IDS:
            gated_out += 1
            reason = f"game_type:{GAME_TYPE_MAP.get(game_type, game_type)}"
            gate_reasons[reason] = gate_reasons.get(reason, 0) + 1
            continue
        admitted.append(raw)

    outcome = await _write_games(admitted, "incremental_games")

    newest = _newest_timestamp(raw_list, "created_at")
    cursor = newest or since
    await _advance_game_watermark(_WATERMARK_CREATED_AT, cursor)

    saturated = len(raw_list) >= max_items
    if saturated:
        logger.info(
            "incremental_games: created lane hit its %d-item ceiling — the watermark "
            "advanced to %s and the next run continues from there",
            max_items,
            cursor.isoformat(),
        )
    result = {
        "since": since.isoformat(),
        "cold_start": cold_start,
        "considered": len(raw_list),
        "gated_out": gated_out,
        "admitted": outcome["written"],
        "errors": outcome["errors"],
        "saturated": saturated,
        "covered_through": cursor.isoformat(),
    }
    if gate_reasons:
        result["gate_reasons"] = gate_reasons
    logger.info("incremental_games: created lane — %s", result)
    return result


async def _incremental_updated_games(*, now: datetime) -> dict:
    """Lane 2 — games whose IGDB record changed since the watermark.

    Refresh only.  An id IGDB reports as updated is re-written **only** if the
    catalog already holds it; the rest never passed the ranking bar and an
    ``updated_at`` bump is no argument that they now should.  That keeps this
    lane's cost proportional to the catalog instead of to IGDB.
    """
    since = await _read_game_watermark(_WATERMARK_UPDATED_AT)
    cold_start = since is None
    if since is None:
        since = now - timedelta(days=max(1, settings.IGDB_INCREMENTAL_LOOKBACK_DAYS))

    max_items = max(1, settings.IGDB_INCREMENTAL_MAX_ITEMS)
    raw_list = await _igdb_client.get_games_updated_since(since, limit=max_items)

    external_ids = [str(raw["id"]) for raw in raw_list if raw.get("id")]
    async with async_session_factory() as session:
        catalogued = await filter_catalogued_external_ids(session, "GAME", "IGDB", external_ids)

    known = [raw for raw in raw_list if str(raw.get("id")) in catalogued]
    outcome = await _write_games(known, "incremental_games")

    newest = _newest_timestamp(raw_list, "updated_at")
    cursor = newest or since
    await _advance_game_watermark(_WATERMARK_UPDATED_AT, cursor)

    result = {
        "since": since.isoformat(),
        "cold_start": cold_start,
        "considered": len(raw_list),
        "unknown": len(raw_list) - len(known),
        "refreshed": outcome["written"],
        "errors": outcome["errors"],
        "saturated": len(raw_list) >= max_items,
        "covered_through": cursor.isoformat(),
    }
    logger.info("incremental_games: updated lane — %s", result)
    return result


async def _incremental_game_promotion() -> dict:
    """Lane 3 — re-enumerate the whole IGDB filter so promotions enter.

    The exact counterpart of :func:`_incremental_promotion` on the TMDB side,
    and it exists for the same reason: the bar a game has to clear is
    ``rating > 0``, and a game crosses it with **no publication event at all**,
    just by someone rating it.  Neither of the other two lanes can see that —
    ``CREATED_AT`` only reports games that are new to IGDB, and ``UPDATED_AT``
    refuses ids the catalog does not already hold, by design.  Until issue #34
    this lane *was* an operator running ``scripts/seed_igdb_targets.py`` by
    hand, which made the promotion delay the gap between two human decisions.

    It writes **no catalog rows**: the walk upserts into ``seed_targets`` and
    the nightly ``sync_games`` hydrates the difference against ``external_ids``
    with no further intervention.  Re-enumerating is idempotent — an existing
    target keeps its ``attempts`` and its ``discovered_at`` — so running this
    every night adds the delta (a few dozen ids a day) and costs the requests
    and nothing else.

    It carries no watermark, and that is not an omission: the sweep has no
    "since".  It asks a question about the present state of the filter (which
    ids clear ``rating > 0`` today) whose answer does not depend on when it was
    last asked, so there is nothing to resume.  The whole walk is **64 requests
    and 52 s** (measured end to end on 2026-09-09; 16 s of that is the 4 req/s
    floor), which is what makes running it nightly cheaper than maintaining an
    argument about when it is worth running.

    ``stalled`` is counted as an **error** rather than reported as a statistic:
    it means a page came back with no id above the keyset cursor, which cannot
    happen with ``sort id asc``, so the enumerated list is incomplete — and a
    catalog that silently stops growing would be indistinguishable from "those
    games no longer pass the filter".  Surfacing it in ``errors`` is what makes
    ``scripts/incremental_sync.py`` finish degraded (exit 2), the same signal
    ``scripts/seed_igdb_targets.py`` gives with its own exit code 2.
    """
    logger.info("incremental_games: promotion sweep — re-enumerating the IGDB catalog filter")

    stats: IgdbEnumerationStats = await enumerate_catalog(
        fetch_page=_igdb_client.get_catalog_page,
        on_targets=partial(_persist_promotion_targets, "GAME"),
        page_size=IGDB_PAGE_SIZE,
    )

    async with async_session_factory() as session:
        progress = await count_seed_target_progress(
            session,
            "GAME",
            SEED_TARGET_SOURCES["GAME"],
            max(1, settings.TMDB_SEED_MAX_ATTEMPTS),
        )

    if stats.stalled:
        logger.error(
            "incremental_games: the promotion sweep stalled at id %d after %d page(s) — the "
            "enumerated list is INCOMPLETE and this run is degraded; re-run "
            "scripts/seed_igdb_targets.py --start-after %d once the query is understood",
            stats.last_id,
            stats.pages,
            stats.last_id,
        )

    result = {
        "pages": stats.pages,
        "enumerated": stats.targets,
        "last_id": stats.last_id,
        "stalled": stats.stalled,
        "pending_after": progress.pending,
        "stuck_after": progress.stuck,
        # A stalled walk is a failed walk, so it travels to the job summary as
        # an error and not as a flag somebody has to go looking for.
        "errors": 1 if stats.stalled else 0,
    }
    logger.info("incremental_games: promotion lane — %s", result)
    return result


async def sync_games_incremental() -> dict:
    """Run the IGDB incremental: new games, changed games and promotion.

    Not part of the nightly slice and not exposed over HTTP — same reasoning as
    the TMDB incrementals: this runs from GitHub Actions straight against Neon
    (``scripts/incremental_sync.py``), where no request cap applies.

    The three lanes are isolated: an exception in one is logged, counted in
    ``errors`` and does not stop the others (checkpoint C19).  They are
    sequential rather than concurrent because they share IGDB's 4 req/s budget,
    and the promotion sweep goes **last** because it is the longest lane and
    the only one with nothing to resume from.  The other two are not a single
    request each: ``get_games_created_since`` / ``get_games_updated_since``
    paginate internally, so after a few missed nights they walk several pages
    apiece.  But their cost is bounded by the *delta* since their watermark,
    while the sweep re-walks the whole filter (~64 requests) every night
    regardless of how quiet the day was.  So it goes last: if the run is cut
    short there, the two watermarked lanes have already covered their ground
    and tomorrow's sweep asks the same question again.

    ``synced`` counts written catalog rows only — admissions plus refreshes.
    The promotion lane writes none by design (it only enumerates targets), so
    it contributes to ``errors`` but never to ``synced``, exactly as on the
    TMDB side.
    """
    logger.info("incremental_games: starting")
    get_metrics().inc_counter("backlogg_syncs_total", labels={"type": "game"})
    start = time.monotonic()
    now = datetime.now(UTC)

    lanes: dict[str, Callable[[], Awaitable[dict]]] = {
        "new_games": partial(_incremental_new_games, now=now),
        "updated_games": partial(_incremental_updated_games, now=now),
        "promotion": _incremental_game_promotion,
    }
    results: dict[str, dict] = {}
    lane_errors = 0

    with collect_link_skips() as link_skips:
        for name, lane in lanes.items():
            try:
                results[name] = await lane()
            except Exception:
                logger.exception(
                    "incremental_games: lane %s failed — the other lanes continue", name
                )
                results[name] = {"failed": True}
                lane_errors += 1

    errors = lane_errors + sum(int(lane.get("errors", 0)) for lane in results.values())
    synced = int(results.get("new_games", {}).get("admitted", 0)) + int(
        results.get("updated_games", {}).get("refreshed", 0)
    )
    summary = {
        "item_type": "GAME",
        "synced": synced,
        "errors": errors,
        "people_errors": 0,
        "skipped_links": link_skips.count,
        "duration_s": round(time.monotonic() - start, 1),
        "new_games": results["new_games"],
        "updated_games": results["updated_games"],
        "promotion": results["promotion"],
    }
    logger.info(
        "incremental_games: done — %d game(s) written, %d error(s), %d skipped_links in %.1fs",
        synced,
        errors,
        link_skips.count,
        summary["duration_s"],
    )
    return summary


# ── Targeted credits backfill (feature 85) ───────────────────────────────────
#
# The jobs above walk the external API's *popularity ranking*.  That is the
# wrong instrument for filling credit holes (issue #15): the items missing
# credits entered the catalog through other paths (search fan-out, trending,
# /similar) and sit at arbitrary ranking positions — or outside the ranking
# altogether — so thousands of positions can be walked without touching a
# single one of them.  ``sync_missing_credits`` is driven by the *local*
# catalog instead: the work list is the gap query in
# ``scheduler/repository.get_credit_gaps``, which converges by construction
# and is bounded by the real hole.
#
# Three deliberate differences from the jobs above:
#
# 1. **No item detail is fetched or re-written.**  The row already exists;
#    only its credits are missing.  One HTTP call per item, and the write
#    goes through ``bulk_load_credits`` (the credits half of the feature-84
#    batch route), never through the item upsert.
# 2. **No ``sync_cursors``.**  There is no ranking to resume: the stop
#    condition is "gap list exhausted" or "time budget spent".
# 3. **``credits_synced_at`` is stamped after every *successful* fetch**,
#    with or without credits, so items that legitimately have none are
#    visited once instead of on every run.  A failed fetch stamps nothing
#    and counts in ``people_errors``.

# Fetch concurrency, mirroring the search fan-out's ``Semaphore`` + ``gather``
# pattern (``backlogg/search/service.py``).  TMDB documents ~50 req/s and
# ``docs/seeding-plan.md`` §4 recommends staying at 30-40, well above what 8
# in-flight detail calls produce.  Open Library is unauthenticated, throttles
# harder, and spends one extra ``/authors/{id}`` call per author inside each
# task, so it gets a lower bound.
_CREDITS_FETCH_CONCURRENCY: dict[str, int] = {"MOVIE": 8, "SERIES": 8, "BOOK": 4}


async def _fetch_movie_credit_rows(external_id: str) -> list[BulkPerson]:
    """``/movie/{id}/credits`` — the only call this item needs."""
    return await collect_movie_credits(int(external_id))


async def _fetch_series_credit_rows(external_id: str) -> list[BulkPerson]:
    """``/tv/{id}?append_to_response=credits`` — cast *and* creators, one call.

    CREATOR credits come from ``created_by``, which lives in the detail
    payload and not in ``/tv/{id}/credits``; ``append_to_response`` brings
    both back for the price of the single request (``docs/seeding-plan.md``
    §4).  The detail body is used only for those two keys — the series row
    itself is deliberately not re-mapped nor re-written.
    """
    detail = await _tmdb_series.get_series_detail(int(external_id), append_to_response="credits")
    if not detail:
        return []
    rows = map_series_credits(detail.get("credits"))
    rows += collect_series_creators(detail.get("created_by", []))
    return rows


async def _fetch_book_credit_rows(external_id: str) -> list[BulkPerson]:
    """Open Library work detail + its authors."""
    work_detail = await _ol_client.get_work_detail(external_id)
    if not work_detail:
        return []
    return await collect_book_authors(work_detail)


_CREDIT_FETCHERS = {
    "MOVIE": _fetch_movie_credit_rows,
    "SERIES": _fetch_series_credit_rows,
    "BOOK": _fetch_book_credit_rows,
}


async def _fetch_credits_guarded(
    sem: asyncio.Semaphore, item_type: str, gap: CreditGap
) -> list[BulkPerson]:
    """Fetch one item's credits under *sem*; exceptions propagate to ``gather``.

    Errors are **not** swallowed here on purpose: the caller has to tell a
    failed fetch (retry next run, ``people_errors``) from a successful one
    that returned nothing (stamp ``credits_synced_at`` and never look again).
    """
    async with sem:
        return await _CREDIT_FETCHERS[item_type](gap.external_id)


async def _write_credits_individually(
    session,
    item_type: str,
    people_by_item: dict[int, list[BulkPerson]],
    item_ids: list[int],
    now: datetime,
) -> tuple[int, int]:
    """Per-item fallback for a credits batch that failed — same contract as
    ``_write_items_individually``: a batch failure costs speed, never data.

    Returns ``(credits_written, people_errors)``.
    """
    written = 0
    errors = 0
    for item_id in item_ids:
        people = people_by_item.get(item_id, [])
        try:
            await _persist_people_individually(session, item_type, item_id, people)
            await mark_credits_synced(session, item_type, [item_id], now)
            await session.commit()
            written += len(people)
        except Exception:
            logger.exception(
                "sync_missing_credits: failed to persist credits for %s id=%s", item_type, item_id
            )
            errors += 1
            await rollback_quietly(session, "sync_missing_credits")
    return written, errors


async def _write_credits_batch(
    session,
    item_type: str,
    entries: list[tuple[int, list[BulkPerson]]],
    item_ids: list[int],
) -> tuple[int, int]:
    """Write one chunk of credits + stamp ``credits_synced_at``, atomically.

    The stamp travels in the same transaction as the credits it certifies: a
    rollback must not leave an item marked as done with no credits written.
    Returns ``(credits_written, people_errors)``.
    """
    if not item_ids:
        return 0, 0
    now = datetime.now(UTC)
    try:
        outcome = await bulk_load_credits(session, item_type, entries)
        await mark_credits_synced(session, item_type, item_ids, now)
        await session.commit()
        # The batch wrote with raw SQL: drop anything stale in the identity map.
        session.expunge_all()
    except Exception:
        logger.exception(
            "sync_missing_credits: batch of %d items failed — retrying per item",
            len(item_ids),
        )
        await rollback_quietly(session, "sync_missing_credits")
        return await _write_credits_individually(session, item_type, dict(entries), item_ids, now)

    if outcome.people_rejected:
        logger.warning(
            "sync_missing_credits: batch dropped %d invalid credits", outcome.people_rejected
        )
    return outcome.people_written, outcome.people_rejected


async def sync_missing_credits(
    content_type: str,
    *,
    recheck: bool = False,
    time_budget_s: float | None = None,
    concurrency: int | None = None,
) -> dict:
    """Fill the credit holes of ``content_type``, driven by the local catalog.

    ``content_type`` is the lowercase CLI name (``movie``/``series``/
    ``book``); ``game`` is rejected — games have no people-credit ingestion
    at all, only company credits that travel inside the item payload.

    Work list: every item with zero rows in ``credits`` and (unless
    ``recheck``) a NULL ``credits_synced_at``.  Items with no external id for
    the type's source cannot be fetched and are reported in
    ``skipped_no_external_id`` instead of failing the run.

    Processing: chunks of ``BULK_LOAD_BATCH_SIZE``.  Inside a chunk the
    fetches run in parallel under a ``Semaphore`` (same pattern as the search
    fan-out) and the write is sequential — ``AsyncSession`` is not safe for
    concurrent use.

    Returns a summary dict with ``content_type``, ``considered``,
    ``processed``, ``with_credits``, ``sealed_without_credits``,
    ``credits_written``, ``people_errors``, ``skipped_links``,
    ``skipped_no_external_id``, ``duration_s`` and ``stop_reason``
    (``"exhausted"`` or ``"time_budget"``).

    ``skipped_links`` counts the *people* links this pass could not write
    because the TMDB/Open Library person id was already claimed by another
    ``people`` row — the credit still lands, but that person stays unresolvable
    by external id.
    """
    item_type = _ITEM_TYPES_BY_CONTENT.get(content_type)
    if item_type is None or item_type not in CREDIT_GAP_SOURCES:
        raise ValueError(
            f"sync_missing_credits: unsupported content type {content_type!r} — "
            f"supported: {', '.join(sorted(_CREDIT_FETCHERS))} (lowercased). "
            "games have no people credits, only company credits."
        )

    # Deliberately not incrementing ``backlogg_syncs_total``: that series
    # counts catalog syncs, and a targeted credits pass syncs no item.
    start = time.monotonic()

    async with async_session_factory() as session:
        gap_set = await get_credit_gaps(session, item_type, recheck=recheck)

    logger.info(
        "sync_missing_credits %s: %d items without credits (%d workable, "
        "%d without external id), recheck=%s",
        content_type,
        gap_set.considered,
        len(gap_set.gaps),
        gap_set.skipped_no_external_id,
        recheck,
    )

    limit = concurrency or _CREDITS_FETCH_CONCURRENCY.get(item_type, 5)
    sem = asyncio.Semaphore(limit)
    chunk_size = max(1, settings.BULK_LOAD_BATCH_SIZE)

    processed = 0
    with_credits = 0
    sealed_without_credits = 0
    credits_written = 0
    people_errors = 0
    stop_reason = "exhausted"

    with collect_link_skips() as link_skips:
        async with async_session_factory() as session:
            for start_index in range(0, len(gap_set.gaps), chunk_size):
                if time_budget_s is not None and time.monotonic() - start >= time_budget_s:
                    stop_reason = "time_budget"
                    break

                chunk = gap_set.gaps[start_index : start_index + chunk_size]

                # Fetch phase — parallel, bounded by the semaphore.
                fetched = await asyncio.gather(
                    *(_fetch_credits_guarded(sem, item_type, gap) for gap in chunk),
                    return_exceptions=True,
                )

                # Persist phase — sequential: AsyncSession is not concurrency-safe.
                entries: list[tuple[int, list[BulkPerson]]] = []
                item_ids: list[int] = []
                for gap, outcome in zip(chunk, fetched, strict=True):
                    if isinstance(outcome, BaseException):
                        logger.warning(
                            "sync_missing_credits %s: fetch failed for external_id=%s (%s) — "
                            "not stamping, will retry next run",
                            content_type,
                            gap.external_id,
                            outcome,
                        )
                        people_errors += 1
                        continue
                    item_ids.append(gap.item_id)
                    if outcome:
                        entries.append((gap.item_id, outcome))
                        with_credits += 1
                    else:
                        sealed_without_credits += 1

                written, errors = await _write_credits_batch(session, item_type, entries, item_ids)
                credits_written += written
                people_errors += errors
                processed += len(item_ids)

                logger.info(
                    "sync_missing_credits %s: %d/%d items processed, %d credits written, "
                    "%d people_errors, %d skipped_links (%.0fs elapsed)",
                    content_type,
                    processed,
                    len(gap_set.gaps),
                    credits_written,
                    people_errors,
                    link_skips.count,
                    time.monotonic() - start,
                )

    skipped_links = link_skips.count
    return {
        "content_type": content_type,
        "considered": gap_set.considered,
        "processed": processed,
        "with_credits": with_credits,
        "sealed_without_credits": sealed_without_credits,
        "credits_written": credits_written,
        "people_errors": people_errors,
        "skipped_links": skipped_links,
        "skipped_no_external_id": gap_set.skipped_no_external_id,
        "duration_s": round(time.monotonic() - start, 1),
        "stop_reason": stop_reason,
    }
