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

**Issue #24 — the other loss, on the other key.**  ``skipped_links`` is about
``uq_external_id``: two items fighting over one external id.  Its mirror image
is ``uq_item_source``: one *row* holding two external ids of the same source,
which the constraint does not allow either.  It happens when two distinct
source identities collapse onto a single catalog row — two people whose names
slugify the same, so ``_resolve_people`` returns the same ``people.id`` for two
different TMDB ids — and also when the source re-points an item at a new id.
Whichever external id arrives second wins the row and the other one is dropped:
the item stays linked, but one of the two ids can never be resolved again.

That loss was invisible by construction, and specifically invisible to
``skipped_links``, which discards the ``by_item`` collision by design (there
the ``item_id`` is the *same*, which is the discriminant it uses for
idempotency).  It is now its own class of skip — ``record_identity_skip``,
counted in ``LinkSkipCollector.identity_count`` and reported as
``skipped_identities`` — travelling the exact same road as ``skipped_links``:
collector -> job result dict -> ``POST /admin/sync/{type}`` ->
``scripts/backfill_sync.py`` -> a ``::warning::`` in the nightly workflow.  Two
counters and not one because the remedies differ: a skipped *link* means an
item with no id at all, a skipped *identity* means an item whose id is one of
two.  Merging them would blur the only number that could tell an operator
which of the two is happening.

The *behaviour* is deliberately unchanged: two homonyms are still one row
(2026-09-12 product decision).  What changes is that the catalog now says so.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_TRACKED_LINK_SKIPS",
    "ExternalId",
    "IdentitySkip",
    "LinkSkip",
    "LinkSkipCollector",
    "collect_link_skips",
    "get_external_id",
    "record_identity_skip",
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


@dataclass(frozen=True, slots=True)
class IdentitySkip:
    """One external id a row could not keep, because it already holds another.

    ``uq_item_source`` allows a single external id per ``(item_type, item_id,
    source)``.  When two source identities resolve to the same catalog row —
    two homonymous people, most often — the second one to arrive takes the
    link and ``dropped_external_id`` becomes unresolvable.

    ``kept_external_id`` is the winner (the row is linked to it),
    ``dropped_external_id`` the id nothing points at any more.
    """

    item_type: str
    source: str
    item_id: int
    kept_external_id: str
    dropped_external_id: str


@dataclass(slots=True)
class LinkSkipCollector:
    """Accumulator for the skips happening inside one ``collect_link_skips``.

    Holds both classes (issues #22 and #24).  One collector and not two because
    they are recorded by the same two write paths, inside the same block, and a
    second ``ContextVar`` would double the setup for nothing — but the counters
    stay separate, because the two losses are different and are reported under
    different names.
    """

    count: int = 0
    skips: list[LinkSkip] = field(default_factory=list)
    identity_count: int = 0
    identity_skips: list[IdentitySkip] = field(default_factory=list)

    def add(self, skip: LinkSkip) -> None:
        self.count += 1
        if len(self.skips) < MAX_TRACKED_LINK_SKIPS:
            self.skips.append(skip)

    def add_identity(self, skip: IdentitySkip) -> None:
        self.identity_count += 1
        if len(self.identity_skips) < MAX_TRACKED_LINK_SKIPS:
            self.identity_skips.append(skip)


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


def record_identity_skip(
    item_type: str,
    source: str,
    item_id: int,
    kept_external_id: str,
    dropped_external_id: str,
) -> None:
    """Log an external id a row could not keep, and count it if a collector is active.

    The ``uq_item_source`` half of the instrumentation (issue #24).  Same
    contract as ``record_link_skip``: never raises, never requires a collector,
    always logs.  Only called when the two ids actually differ — re-offering
    the id a row already holds is idempotency and stays silent, exactly like
    the link case.
    """
    logger.warning(
        "external_ids: identity skipped — %s item_id=%s (%s) keeps external_id=%s, so %s "
        "is dropped; two source identities resolved to one catalog row and "
        "uq_item_source only fits one of them (issue #24)",
        item_type,
        item_id,
        source,
        kept_external_id,
        dropped_external_id,
    )
    collector = _link_skips.get()
    if collector is None:
        return
    collector.add_identity(
        IdentitySkip(
            item_type=item_type,
            source=source,
            item_id=item_id,
            kept_external_id=kept_external_id,
            dropped_external_id=dropped_external_id,
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
    #
    # The ``or_`` branch reads the *other* unique key of the table in the same
    # round trip (issue #24): the row this item already holds for this source,
    # if any. Nothing below changes because of it — the write is the same
    # ``ON CONFLICT ON CONSTRAINT uq_item_source DO UPDATE`` it always was — but
    # that update silently replaces an existing external id, and without this
    # read there is no way to say which id was dropped. One query with two
    # indexable branches (Postgres bitmap-ORs ``uq_external_id`` and
    # ``idx_external_ids_item``), not a second round trip.
    existing_check = await db.execute(
        select(ExternalId).where(
            ExternalId.item_type == item_type,
            ExternalId.source == source,
            or_(ExternalId.external_id == external_id, ExternalId.item_id == item_id),
        )
    )
    candidates = existing_check.scalars().all()
    existing_row = next((row for row in candidates if row.external_id == external_id), None)
    if existing_row is None:
        # No row holds this id, so the insert below will go through — but if
        # this item already carries a *different* id of the same source, the
        # ON CONFLICT update overwrites it and that id stops being resolvable.
        # Behaviour unchanged on purpose (the newcomer still wins); the loss is
        # now counted instead of silent.
        held = next((row for row in candidates if row.item_id == item_id), None)
        if held is not None:
            record_identity_skip(item_type, source, item_id, external_id, held.external_id)
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
