"""Polymorphic ``external_ids`` helpers + the link-skip collector (issue #22).

Both write paths for ``external_ids`` — this module's ``upsert_external_id``
and the batch ``_upsert_external_ids`` in ``backlogg.shared.bulk_load`` —
pre-check ``(item_type, source, external_id)`` and let the **first claim win**
when the triple is already taken by a *different* item of the same type.  That
rule is deliberate (it is what keeps ``uq_external_id`` from raising), but
until issue #22 it was also invisible: the item row was written, its link never
was, and nothing said so.  The exact same blindness produced issues #7, #15 and
#20, each found by accident months later.

What is instrumented here is only the *loss*, never the idempotent case: the
same TMDB person appears in cast and crew of the same movie, and re-running a
slice re-offers links that already exist.  Those hit the very same pre-check
and must stay silent, otherwise the counter is noise.  The discriminant is
``existing_row.item_id``: equal to the caller's item means idempotency, a
different item means a link the catalog wanted and did not get.

The counter is a ``ContextVar`` rather than an extra return value because
``upsert_external_id`` has eleven callers across movies, series, books, games,
trending, people and the scheduler, and *none* of them is the code that
reports: between the helper and the dict a sync job returns there are the
per-domain services.  Threading ``(row, skipped)`` through all of them would
change signatures nobody but the job reads.  Being a ``ContextVar`` also makes
it task-local, so two concurrent jobs never mix counters.

Outside an active ``collect_link_skips()`` block recording a skip is a **no-op**
for the counter: the on-demand paths (search fan-out, ``GET /movies/{slug}``,
``/similar``) pay nothing and cannot fail on it.  The ``logger.warning`` is
emitted either way — a lost link deserves a log line whoever triggered it.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_TRACKED_LINK_SKIPS",
    "ExternalId",
    "LinkSkip",
    "LinkSkipCollector",
    "collect_link_skips",
    "get_external_id",
    "record_link_skip",
    "set_external_id",
    "upsert_external_id",
]

# How many individual skips a collector keeps the detail of.  The *count* is
# always exact; only the per-skip tuples are capped, so a systemic failure
# during a 118.850-item seeding run cannot grow an unbounded list in memory.
# Every skip is logged regardless, so nothing is truly lost by the cap.
MAX_TRACKED_LINK_SKIPS = 100


@dataclass(frozen=True, slots=True)
class LinkSkip:
    """One link the catalog wanted and did not get.

    ``attempted_item_id`` is the pretender (its row exists, unlinked);
    ``claimed_by_item_id`` is the incumbent that keeps the triple.
    """

    item_type: str
    source: str
    external_id: str
    attempted_item_id: int
    claimed_by_item_id: int


@dataclass(slots=True)
class LinkSkipCollector:
    """Accumulator for the skips happening inside one ``collect_link_skips``."""

    count: int = 0
    skips: list[LinkSkip] = field(default_factory=list)

    def add(self, skip: LinkSkip) -> None:
        self.count += 1
        if len(self.skips) < MAX_TRACKED_LINK_SKIPS:
            self.skips.append(skip)


_link_skips: ContextVar[LinkSkipCollector | None] = ContextVar("backlogg_link_skips", default=None)


@contextmanager
def collect_link_skips() -> Iterator[LinkSkipCollector]:
    """Count the links skipped by either write path inside this block.

    Nests safely: an inner block gets its own collector and the outer one is
    restored on exit (the token is reset in ``finally``).  Tasks spawned inside
    the block inherit the context, so ``asyncio.gather`` fan-outs count into
    the same collector.
    """
    collector = LinkSkipCollector()
    token = _link_skips.set(collector)
    try:
        yield collector
    finally:
        _link_skips.reset(token)


def record_link_skip(
    item_type: str,
    source: str,
    external_id: str,
    attempted_item_id: int,
    claimed_by_item_id: int,
) -> None:
    """Log a lost link and count it if a collector is active.

    Never raises and never requires a collector: the logging half runs on every
    path, the counting half only inside ``collect_link_skips()``.
    """
    logger.warning(
        "external_ids: link skipped — %s (%s, %s) wanted by item_id=%s is already "
        "claimed by item_id=%s; the pretender keeps no external id",
        item_type,
        source,
        external_id,
        attempted_item_id,
        claimed_by_item_id,
    )
    collector = _link_skips.get()
    if collector is None:
        return
    collector.add(
        LinkSkip(
            item_type=item_type,
            source=source,
            external_id=external_id,
            attempted_item_id=attempted_item_id,
            claimed_by_item_id=claimed_by_item_id,
        )
    )


class ExternalId(Base):
    __tablename__ = "external_ids"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Unique **per item type**: TMDB numbers movies, series and people in
        # independent sequences that overlap, so id 110531 can legitimately be
        # both a person and a series.  Leaving ``item_type`` out of this key
        # made the first claimant of a number block every other type from ever
        # being linked — silently, since both upsert paths pre-check and skip
        # (issue #20).
        UniqueConstraint("item_type", "source", "external_id", name="uq_external_id"),
        UniqueConstraint("item_type", "item_id", "source", name="uq_item_source"),
        Index("idx_external_ids_item", "item_type", "item_id"),
    )


async def get_external_id(
    db: AsyncSession, item_type: str, item_id: int, source: str
) -> ExternalId | None:
    result = await db.execute(
        select(ExternalId).where(
            ExternalId.item_type == item_type,
            ExternalId.item_id == item_id,
            ExternalId.source == source,
        )
    )
    return result.scalar_one_or_none()


async def set_external_id(
    db: AsyncSession, item_type: str, item_id: int, source: str, external_id: str
) -> ExternalId:
    record = ExternalId(
        item_type=item_type,
        item_id=item_id,
        source=source,
        external_id=external_id,
    )
    db.add(record)
    await db.flush()
    return record


async def upsert_external_id(
    db: AsyncSession, item_type: str, item_id: int, source: str, external_id: str
) -> ExternalId:
    # Check first if this (item_type, source, external_id) triple already
    # exists. Prevents uq_external_id IntegrityError when the same external ID
    # appears more than once (e.g. same TMDB person in cast and crew).
    #
    # ``item_type`` is part of the lookup because it is part of the constraint:
    # without it, a PERSON row claiming TMDB id 110531 made the *series* 110531
    # unlinkable forever, and this pre-check returned that unrelated PERSON row
    # instead of raising (issue #20). Two items of *different* types may now
    # share a number; two items of the *same* type still may not, and for that
    # case the pre-check keeps its original semantics — first claim wins.
    existing_check = await db.execute(
        select(ExternalId).where(
            ExternalId.item_type == item_type,
            ExternalId.source == source,
            ExternalId.external_id == external_id,
        )
    )
    existing_row = existing_check.scalar_one_or_none()
    if existing_row is not None:
        # Already linked to an item of this type. Two very different cases hide
        # behind this single branch and issue #22 is about telling them apart:
        #
        # * same ``item_id`` — pure idempotency (the same TMDB person in cast
        #   and crew, a re-run of a slice). Nothing is lost, nothing is said.
        # * different ``item_id`` — the caller's item will never get a link.
        #   First claim still wins (changing the owner is a data decision, not
        #   an instrumentation one), but the loss is now logged and counted.
        if existing_row.item_id != item_id:
            record_link_skip(item_type, source, external_id, item_id, existing_row.item_id)
        return existing_row

    # Not yet linked — safe to insert.
    stmt = (
        insert(ExternalId)
        .values(
            item_type=item_type,
            item_id=item_id,
            source=source,
            external_id=external_id,
        )
        .on_conflict_do_update(
            constraint="uq_item_source",
            set_={"external_id": external_id},
        )
        .returning(ExternalId)
    )
    result = await db.execute(stmt)
    await db.flush()
    row = result.scalar_one()
    await db.refresh(row)
    return row
