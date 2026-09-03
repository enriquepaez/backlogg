"""Scheduler repository — persistence for the sync/backfill data access.

Only this module touches SQLAlchemy for the ``sync_cursors`` table, for the
credits-gap query that drives the targeted backfill (feature 85) and for the
``seed_targets`` work list that drives the TMDB seeding (feature 86).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books.models import Book
from backlogg.movies.models import Movie
from backlogg.series.models import Series
from backlogg.shared.external_ids import ExternalId
from backlogg.shared.models import Credit, SeedTarget, SyncCursor

__all__ = [
    "CREDIT_GAP_SOURCES",
    "SEED_TARGET_SOURCES",
    "CreditGap",
    "CreditGaps",
    "SeedTargetProgress",
    "SeedTargetRow",
    "count_seed_target_progress",
    "count_seed_targets",
    "get_credit_gaps",
    "get_pending_seed_targets",
    "get_stale_catalog_external_ids",
    "get_sync_offset",
    "mark_credits_synced",
    "mark_seed_targets_attempted",
    "mark_seed_targets_unreachable",
    "set_sync_offset",
    "upsert_seed_targets",
]

# Item types that can have people credits backfilled, with the external
# source their id has to be resolved against.  GAME is deliberately absent:
# games only carry *company* credits (developer/publisher), which travel
# inside the item payload itself and never reach the ``credits`` table.
CREDIT_GAP_SOURCES: dict[str, str] = {
    "MOVIE": "TMDB",
    "SERIES": "TMDB",
    "BOOK": "OPEN_LIBRARY",
}

_ITEM_MODELS: dict[str, Any] = {
    "MOVIE": Movie,
    "SERIES": Series,
    "BOOK": Book,
}


@dataclass(frozen=True, slots=True)
class CreditGap:
    """One catalog item that has no credits and a resolvable external id."""

    item_id: int
    external_id: str


@dataclass(frozen=True, slots=True)
class CreditGaps:
    """Result of the credits-gap query for one item type.

    ``gaps`` are the items that can actually be worked on.  Items with no
    external id for the relevant source cannot be fetched at all — they are
    counted in ``skipped_no_external_id`` instead of raising, so one
    unlinked row never takes a run down.  ``considered`` is the size of the
    whole gap set (workable + skipped).
    """

    gaps: list[CreditGap]
    skipped_no_external_id: int

    @property
    def considered(self) -> int:
        return len(self.gaps) + self.skipped_no_external_id


async def get_sync_offset(db: AsyncSession, item_type: str) -> int:
    """Return the persisted next offset for ``item_type``, or 0 if absent."""
    result = await db.execute(
        select(SyncCursor.next_offset).where(SyncCursor.item_type == item_type)
    )
    offset = result.scalar_one_or_none()
    return offset if offset is not None else 0


async def set_sync_offset(db: AsyncSession, item_type: str, next_offset: int) -> None:
    """Upsert the next offset for ``item_type`` (idempotent)."""
    stmt = (
        insert(SyncCursor)
        .values(item_type=item_type, next_offset=next_offset)
        .on_conflict_do_update(
            index_elements=[SyncCursor.item_type],
            set_={"next_offset": next_offset, "updated_at": func.now()},
        )
    )
    await db.execute(stmt)
    await db.flush()


async def get_credit_gaps(db: AsyncSession, item_type: str, *, recheck: bool = False) -> CreditGaps:
    """Return the items of ``item_type`` that have no credits yet.

    This is the work list of the targeted backfill (feature 85), and the
    whole point of it: it is driven by the **local catalog**, not by TMDB's
    popularity ranking, so it converges by construction and is bounded by
    the real gap instead of by 10.000 ranking positions.

    Shape of the query:

    - ``LEFT JOIN credits ON (item_type, item_id) ... WHERE credits.id IS
      NULL`` — items with not a single credit row;
    - ``AND credits_synced_at IS NULL`` unless ``recheck`` — items already
      visited by a successful fetch are not retried (see ``docs/schema.md``);
    - ``LEFT JOIN external_ids`` on the source of the type, so the external
      id travels with the row. The join is a LEFT one on purpose: an item
      with no external id is reported in ``skipped_no_external_id`` rather
      than silently dropped or raised on.

    Ordered by item id so a run that stops on its time budget resumes on the
    same, stable sequence.
    """
    model = _ITEM_MODELS.get(item_type)
    if model is None:
        raise ValueError(f"get_credit_gaps: unsupported item_type {item_type!r}")
    source = CREDIT_GAP_SOURCES[item_type]

    stmt = (
        select(model.id, ExternalId.external_id)
        .select_from(model)
        .outerjoin(
            Credit,
            (Credit.item_type == item_type) & (Credit.item_id == model.id),
        )
        .outerjoin(
            ExternalId,
            (ExternalId.item_type == item_type)
            & (ExternalId.item_id == model.id)
            & (ExternalId.source == source),
        )
        .where(Credit.id.is_(None))
        .order_by(model.id)
    )
    if not recheck:
        stmt = stmt.where(model.credits_synced_at.is_(None))
    rows = (await db.execute(stmt)).all()
    gaps = [
        CreditGap(item_id=item_id, external_id=external_id)
        for item_id, external_id in rows
        if external_id
    ]
    skipped = sum(1 for _, external_id in rows if not external_id)
    return CreditGaps(gaps=gaps, skipped_no_external_id=skipped)


async def mark_credits_synced(
    db: AsyncSession, item_type: str, item_ids: list[int], synced_at: datetime
) -> None:
    """Stamp ``credits_synced_at`` on the given items (feature 85).

    Called only after a *successful* credits fetch, with or without rows:
    that is what stops the next run from re-fetching an item that
    legitimately has no credits at the source.  Does not commit.
    """
    if not item_ids:
        return
    model = _ITEM_MODELS.get(item_type)
    if model is None:
        raise ValueError(f"mark_credits_synced: unsupported item_type {item_type!r}")
    await db.execute(
        update(model).where(model.id.in_(item_ids)).values(credits_synced_at=synced_at)
    )


# ── Seed targets (feature 86) ────────────────────────────────────────────────
#
# Item types whose catalog is defined by an enumerated target list instead of
# by an offset into a popularity ranking, with the external source the ids
# belong to.  BOOK and GAME are absent on purpose: their enumerations are
# unchanged (Open Library's filtered search and IGDB's single bulk query) and
# still use ``sync_cursors``.
SEED_TARGET_SOURCES: dict[str, str] = {
    "MOVIE": "TMDB",
    "SERIES": "TMDB",
}

# How many rows one INSERT ... ON CONFLICT statement carries. Each row spends
# 5 bind parameters and Postgres caps a statement at 32.767 of them, so 1.000
# rows = 5.000 parameters leaves a wide margin.
_SEED_TARGET_CHUNK = 1000


@dataclass(frozen=True, slots=True)
class SeedTargetRow:
    """One row of the enumerated target list, ready to persist."""

    item_type: str
    source: str
    external_id: str
    vote_count: int | None = None
    release_year: int | None = None


async def upsert_seed_targets(db: AsyncSession, rows: Sequence[SeedTargetRow]) -> int:
    """Upsert enumerated targets, returning how many rows were sent.

    Multi-row ``INSERT ... ON CONFLICT DO UPDATE`` in chunks — one statement
    per chunk, not one per row.  Deliberately *not* routed through
    ``backlogg.shared.bulk_load``: that module exists to write catalog items
    together with their people, credits, external ids and genre joins across
    six tables, and every one of its moving parts (COPY into temp tables,
    per-batch person resolution, the per-item fallback) would be dead weight
    for a five-column flat table with a natural key.  The hydration this table
    feeds *does* go through ``bulk_load``.

    Re-enumerating is idempotent by design: an existing target keeps its
    ``attempts`` and ``discovered_at`` and only refreshes the two observed
    values, so re-running the enumeration never resets the hydration's
    progress or its anti-starvation ordering.  Does not commit.
    """
    if not rows:
        return 0

    # De-duplicate inside the payload: ON CONFLICT DO UPDATE cannot touch the
    # same row twice in one statement ("cannot affect row a second time").
    unique: dict[tuple[str, str, str], SeedTargetRow] = {}
    for row in rows:
        unique[(row.item_type, row.source, row.external_id)] = row
    values = [
        {
            "item_type": row.item_type,
            "source": row.source,
            "external_id": row.external_id,
            "vote_count": row.vote_count,
            "release_year": row.release_year,
        }
        for row in unique.values()
    ]

    for start in range(0, len(values), _SEED_TARGET_CHUNK):
        chunk = values[start : start + _SEED_TARGET_CHUNK]
        stmt = insert(SeedTarget).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_seed_target",
            set_={
                "vote_count": stmt.excluded.vote_count,
                "release_year": stmt.excluded.release_year,
            },
        )
        await db.execute(stmt)
    await db.flush()
    return len(values)


@dataclass(frozen=True, slots=True)
class SeedTargetProgress:
    """How much of one type's target list is done, left, and stuck.

    ``pending`` is deliberately **workable** pending, not "unlinked": it is the
    number the refresh rotation and the backfill loop key off, so it has to be
    able to reach 0.  Everything that has been retired is reported apart, in
    ``gone`` and ``unlinkable``, so a catalog that cannot converge because of
    the pre-existing global ``uq_external_id`` is *visible* to the operator
    instead of hidden inside a number that never moves.
    """

    total: int
    pending: int
    gone: int
    unlinkable: int

    @property
    def stuck(self) -> int:
        """Targets retired from the work list — enumerated but unreachable."""
        return self.gone + self.unlinkable


def _unlinked_targets_stmt(item_type: str, source: str):
    """``seed_targets`` rows with no matching row in ``external_ids``.

    This is the resume mechanism of the whole feature: **the difference
    between what the catalog wants and what it has**, computed live.  There is
    no offset and no progress marker to get out of sync — a run that dies
    halfway leaves the remaining work correctly described by this query alone.

    The join carries ``item_type`` as well as ``(source, external_id)``
    because the same TMDB id can legitimately be a movie and a series.
    """
    return (
        select(SeedTarget)
        .outerjoin(
            ExternalId,
            (ExternalId.item_type == SeedTarget.item_type)
            & (ExternalId.source == SeedTarget.source)
            & (ExternalId.external_id == SeedTarget.external_id),
        )
        .where(
            SeedTarget.item_type == item_type,
            SeedTarget.source == source,
            ExternalId.id.is_(None),
        )
    )


def _retired_clause(max_attempts: int):
    """A target the work list must skip: 404 at the source, or out of passes.

    Two unrelated causes, both terminal:

    * ``unreachable_at`` — TMDB answered 404. Definitive; nothing will come
      back by asking again.
    * ``attempts >= max_attempts`` — the fetch keeps resolving fine and the
      item keeps *not* getting linked, which in practice means its
      ``(source, external_id)`` pair is already claimed by another item type
      (``uq_external_id`` is global). Retrying forever changes nothing.

    Without this, ``pending`` would have a permanent floor: the refresh
    rotation (which only fires once nothing is pending) would never run and
    the backfill loop would never terminate.
    """
    return SeedTarget.unreachable_at.is_not(None) | (SeedTarget.attempts >= max_attempts)


async def count_seed_targets(db: AsyncSession, item_type: str, source: str) -> int:
    """Total enumerated targets for ``(item_type, source)``."""
    result = await db.execute(
        select(func.count())
        .select_from(SeedTarget)
        .where(SeedTarget.item_type == item_type, SeedTarget.source == source)
    )
    return result.scalar_one()


async def count_seed_target_progress(
    db: AsyncSession, item_type: str, source: str, max_attempts: int
) -> SeedTargetProgress:
    """Return the pending / gone / unlinkable breakdown in a single query."""
    retired = _retired_clause(max_attempts)
    stmt = _unlinked_targets_stmt(item_type, source).with_only_columns(
        func.count().filter(~retired),
        func.count().filter(SeedTarget.unreachable_at.is_not(None)),
        func.count().filter(
            SeedTarget.unreachable_at.is_(None) & (SeedTarget.attempts >= max_attempts)
        ),
    )
    pending, gone, unlinkable = (await db.execute(stmt)).one()
    total = await count_seed_targets(db, item_type, source)
    return SeedTargetProgress(total=total, pending=pending, gone=gone, unlinkable=unlinkable)


async def get_pending_seed_targets(
    db: AsyncSession, item_type: str, source: str, limit: int, max_attempts: int
) -> list[str]:
    """Return up to ``limit`` **workable** external ids missing from the catalog.

    Retired targets (``_retired_clause``) are excluded outright: leaving them
    in would mean re-spending a slice slot and a TMDB request on them every
    single run, forever, for an outcome already known.

    Ordered by ``attempts`` ascending first, so never-tried targets always go
    before ones a previous run could not link, and a struggling target drifts
    behind everything untried during the passes it still has left.  Within the
    same attempt count the order is by ``vote_count`` descending, so the most
    notable items enter the catalog first and an interrupted seeding leaves the
    best of it in.
    """
    if limit <= 0:
        return []
    stmt = (
        _unlinked_targets_stmt(item_type, source)
        .where(~_retired_clause(max_attempts))
        .with_only_columns(SeedTarget.external_id)
        .order_by(
            SeedTarget.attempts.asc(),
            SeedTarget.vote_count.desc().nulls_last(),
            SeedTarget.id.asc(),
        )
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def mark_seed_targets_attempted(
    db: AsyncSession,
    item_type: str,
    source: str,
    external_ids: Sequence[str],
    attempted_at: datetime,
) -> None:
    """Increment ``attempts`` on the targets a slice **conclusively** worked on.

    "Conclusively" is the whole point: only targets whose fetch actually
    resolved are counted.  A fetch that raised (TMDB down, timeout) leaves the
    counter untouched and is retried next run for free — otherwise a long
    outage would burn every target's budget and retire a healthy catalog.

    A target that resolved *and* linked disappears from the work list anyway
    (it now has an ``external_ids`` row), so the counter only ever matters for
    the ones that resolved and did not.  Does not commit.
    """
    if not external_ids:
        return
    await db.execute(
        update(SeedTarget)
        .where(
            SeedTarget.item_type == item_type,
            SeedTarget.source == source,
            SeedTarget.external_id.in_(list(external_ids)),
        )
        .values(attempts=SeedTarget.attempts + 1, last_attempt_at=attempted_at)
    )


async def mark_seed_targets_unreachable(
    db: AsyncSession,
    item_type: str,
    source: str,
    external_ids: Sequence[str],
    observed_at: datetime,
) -> None:
    """Stamp ``unreachable_at`` on targets the source answered 404 for.

    A 404 is a *different* signal from "resolved but did not link", and a
    definitive one: the id was enumerated but TMDB no longer serves it
    (deleted, merged into another entry).  Stamping it on the first
    observation retires the target immediately instead of spending
    ``TMDB_SEED_MAX_ATTEMPTS`` slice slots on an answer that will not change.

    Recorded rather than deleted so a later re-enumeration can tell "never
    seen" from "seen and gone", and so the operator can count them.  Does not
    commit.
    """
    if not external_ids:
        return
    await db.execute(
        update(SeedTarget)
        .where(
            SeedTarget.item_type == item_type,
            SeedTarget.source == source,
            SeedTarget.external_id.in_(list(external_ids)),
        )
        .values(unreachable_at=observed_at, last_attempt_at=observed_at)
    )


async def get_stale_catalog_external_ids(
    db: AsyncSession, item_type: str, source: str, limit: int
) -> list[str]:
    """Return the external ids of the ``limit`` least recently synced items.

    This is the **refresh rotation** (feature 86).  TMDB forbids caching its
    data for more than 6 months (``docs/seeding-plan.md`` §2.3), an obligation
    the old ``/popular`` offset walk covered as a side effect: the cursor
    wrapped around and eventually revisited everything.  Removing the cursor
    would have removed that coverage, so it is replaced by an explicit and
    strictly better rule — once nothing is pending, the nightly slice is
    filled with whatever has gone longest without being re-synced.

    Disjoint from ``get_pending_seed_targets`` by construction: this query
    only returns items that *have* an ``external_ids`` row and that one only
    returns targets that do not.
    """
    if limit <= 0:
        return []
    model = _ITEM_MODELS.get(item_type)
    if model is None:
        raise ValueError(f"get_stale_catalog_external_ids: unsupported item_type {item_type!r}")
    stmt = (
        select(ExternalId.external_id)
        .select_from(model)
        .join(
            ExternalId,
            (ExternalId.item_type == item_type)
            & (ExternalId.item_id == model.id)
            & (ExternalId.source == source),
        )
        .order_by(model.last_synced_at.asc(), model.id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())
