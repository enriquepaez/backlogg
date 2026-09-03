"""Scheduler repository — persistence for the sync/backfill data access.

Only this module touches SQLAlchemy for the ``sync_cursors`` table and for
the credits-gap query that drives the targeted backfill (feature 85).
"""

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
from backlogg.shared.models import Credit, SyncCursor

__all__ = [
    "CREDIT_GAP_SOURCES",
    "CreditGap",
    "CreditGaps",
    "get_credit_gaps",
    "get_sync_offset",
    "mark_credits_synced",
    "set_sync_offset",
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
