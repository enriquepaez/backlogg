"""The two Wikidata passes of feature 79, and the order between them.

**Pass A — the anchor.**  For every catalog item that carries an id of its own
source, ask Wikidata which entity claims that id and persist the answer in
``external_ids`` under ``source='WIKIDATA'``.  This half is worth doing even if
the recommendation block is never unfrozen: it is the *migration policy*
described in the feature.  The day a provider is replaced, an item whose only
identity is a TMDB number is an item whose library history cannot be carried
over; an item that also carries a QID can be remapped mechanically, because
Wikidata holds the new provider's id for the same entity.

**Pass B — the relations.**  For every anchored item, read its ``P144`` /
``P4969`` statements and keep the edges whose *other* end is also anchored,
writing them to ``item_relations``.

B depends on A and the order is not negotiable: the far end of an edge arrives
from Wikidata as a QID and the only way to turn a QID into a catalog row is the
anchor A persisted.  An end that resolves to nothing is **dropped and
counted** — never rescued by matching titles, which is the failure mode this
whole source was chosen to avoid.

Resumability
------------

Both passes walk ``external_ids`` ordered by its primary key and store the last
key they finished in ``sync_watermarks``:

============ ============================ ==========================
source       kind / item_type             ``cursor_value``
============ ============================ ==========================
``WIKIDATA`` ``SPARQL_ANCHOR`` / MOVIE…   last ``external_ids.id``
                                          of that type resolved
``WIKIDATA`` ``SPARQL_RELATIONS`` / ALL   last anchored
                                          ``external_ids.id`` read
============ ============================ ==========================

The cursor advances **after** the batch it describes has been committed, so a
run killed mid-batch redoes that batch and nothing else.  When a pass reaches
the end of its walk it clears its cursor, so the *next* month starts from the
top instead of resuming a finished position — Wikidata keeps being edited, and
a monthly job that only ever looked at rows added since last time would never
pick up a QID somebody filled in for an item the catalog already had.

``item_type='ALL'`` in pass B is the one place the watermark vocabulary is
stretched, and deliberately: the relations walk is a single cursor over every
type at once, because an adaptation edge crosses types by definition and
splitting it per type would need four cursors to describe one walk.

Nothing here writes outside ``external_ids`` (through ``upsert_external_id``,
so the issue #22/#24 skip instrumentation applies unchanged) and
``item_relations`` (through ``upsert_item_relations``, an upsert — no pass ever
issues a ``DELETE``, because feature 83 shares the table).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.recommendations.adapters.wikidata import (
    ANCHOR_PROPERTIES,
    RELATION_PROPERTIES,
    WIKIDATA_QID_BATCH,
    WIKIDATA_VALUES_BATCH,
    WikidataClient,
)
from backlogg.scheduler.repository import (
    WIKIDATA_SOURCE,
    AnchorCoverage,
    get_anchor_coverage,
    get_anchored_batch,
    get_catalog_external_id_batch,
    get_sync_watermark,
    resolve_qids_to_items,
    set_sync_watermark,
)
from backlogg.shared.external_ids import collect_link_skips, upsert_external_id
from backlogg.shared.item_relations import (
    SOURCE_WIKIDATA,
    RelationWrite,
    upsert_item_relations,
)

__all__ = [
    "ANCHOR_KIND",
    "RELATIONS_ITEM_TYPE",
    "RELATIONS_KIND",
    "AnchorPassResult",
    "RelationsPassResult",
    "format_coverage_report",
    "run_anchor_pass",
    "run_relations_pass",
]

logger = logging.getLogger("backlogg.recommendations.wikidata_sync")

ANCHOR_KIND = "SPARQL_ANCHOR"
RELATIONS_KIND = "SPARQL_RELATIONS"
#: See the module docstring: one walk over every type, therefore one cursor.
RELATIONS_ITEM_TYPE = "ALL"

SessionFactory = Callable[[], AsyncSession]


@dataclass(slots=True)
class AnchorPassResult:
    """What one anchor pass did, per content type and in total.

    The four outcome buckets **partition** ``considered`` exactly:
    ``resolved + missing + ambiguous + unlinked == considered``.  That identity
    is the point of ``unlinked`` existing at all — see ``run_anchor_pass`` for
    why counting attempts instead of links was a real hazard.
    """

    considered: int = 0
    resolved: int = 0
    missing: int = 0
    ambiguous: int = 0
    unlinked: int = 0
    skipped_links: int = 0
    skipped_identities: int = 0
    batches: int = 0
    completed: bool = False
    per_type: dict[str, dict[str, int]] = field(default_factory=dict)
    coverage: list[AnchorCoverage] = field(default_factory=list)


@dataclass(slots=True)
class RelationsPassResult:
    """What one relations pass did."""

    anchored_read: int = 0
    statements: int = 0
    written: int = 0
    created: int = 0
    updated: int = 0
    unmatched_ends: int = 0
    self_edges: int = 0
    batches: int = 0
    completed: bool = False
    per_relation: dict[str, int] = field(default_factory=dict)


class _Budget:
    """Wall-clock ceiling for a pass, checked between batches.

    A GitHub Actions job has a hard timeout and a run killed by it leaves no
    summary at all.  Stopping on our own terms keeps the cursor, the counters
    and the coverage report — and the next dispatch continues.
    """

    __slots__ = ("_clock", "deadline")

    def __init__(self, minutes: float, *, clock=time.monotonic) -> None:
        self._clock = clock
        self.deadline = clock() + minutes * 60 if minutes > 0 else None

    def expired(self) -> bool:
        return self.deadline is not None and self._clock() >= self.deadline


async def _read_cursor(db: AsyncSession, kind: str, item_type: str) -> int:
    """The last row id a pass finished, or 0 when it has never run / finished."""
    watermark = await get_sync_watermark(db, WIKIDATA_SOURCE, kind, item_type)
    if watermark is None or watermark.cursor_value is None:
        return 0
    try:
        return int(watermark.cursor_value)
    except ValueError:
        logger.warning(
            "wikidata: unreadable cursor %r for %s/%s — restarting the walk from the top",
            watermark.cursor_value,
            kind,
            item_type,
        )
        return 0


async def _write_cursor(db: AsyncSession, kind: str, item_type: str, cursor: int | None) -> None:
    await set_sync_watermark(
        db,
        WIKIDATA_SOURCE,
        kind,
        item_type,
        cursor_value=None if cursor is None else str(cursor),
        last_run_at=datetime.now(UTC),
    )


async def run_anchor_pass(
    session_factory: SessionFactory,
    *,
    client: WikidataClient | None = None,
    item_types: list[str] | None = None,
    batch_size: int = WIKIDATA_VALUES_BATCH,
    budget_minutes: float = 0.0,
    clock=time.monotonic,
) -> AnchorPassResult:
    """Pass A — resolve catalog ids to QIDs and persist them in ``external_ids``.

    One session and one commit per batch: that is what makes the cursor mean
    "everything up to here is durably written", and it bounds the work a killed
    run has to redo to a single batch.
    """
    client = client or WikidataClient()
    budget = _Budget(budget_minutes, clock=clock)
    result = AnchorPassResult(completed=True)
    types = item_types or list(ANCHOR_PROPERTIES)

    for item_type in types:
        source, property_id = ANCHOR_PROPERTIES[item_type]
        counters = {
            "considered": 0,
            "resolved": 0,
            "missing": 0,
            "ambiguous": 0,
            "unlinked": 0,
        }
        async with session_factory() as session:
            cursor = await _read_cursor(session, ANCHOR_KIND, item_type)

        while True:
            if budget.expired():
                result.completed = False
                logger.warning(
                    "wikidata anchor: time budget exhausted during %s — stopping at "
                    "external_ids.id=%d; re-dispatch to continue",
                    item_type,
                    cursor,
                )
                break

            async with session_factory() as session:
                batch = await get_catalog_external_id_batch(
                    session, item_type, source, cursor, batch_size
                )
            if not batch:
                # Walk finished: clear the cursor so next month starts over.
                async with session_factory() as session:
                    await _write_cursor(session, ANCHOR_KIND, item_type, None)
                    await session.commit()
                break

            resolved = await client.resolve_qids(property_id, [row.external_id for row in batch])
            counters["considered"] += len(batch)
            result.batches += 1

            async with session_factory() as session:
                with collect_link_skips() as collector:
                    for row in batch:
                        qids = resolved.get(row.external_id) or []
                        if not qids:
                            counters["missing"] += 1
                            continue
                        if len(qids) > 1:
                            # Two entities claiming one id. Picking one would be
                            # guessing, and a wrong anchor is worse than none:
                            # it is the thing a future migration would trust.
                            counters["ambiguous"] += 1
                            logger.warning(
                                "wikidata anchor: %s %s=%s is claimed by %d entities (%s) — "
                                "left unanchored rather than guessed",
                                item_type,
                                property_id,
                                row.external_id,
                                len(qids),
                                ", ".join(qids),
                            )
                            continue
                        linked = await upsert_external_id(
                            session, item_type, row.item_id, WIKIDATA_SOURCE, qids[0]
                        )
                        # ``resolved`` counts **links, not attempts**.  When the
                        # QID is already claimed by another item of the same
                        # type, ``upsert_external_id`` keeps the incumbent and
                        # returns *its* row (issue #22): this item ends the pass
                        # with no anchor at all, and reporting it as anchored
                        # would print a number the table cannot back — the exact
                        # silent discrepancy that chained issues #7, #15 and #20.
                        # The ``uq_item_source`` case (issue #24) is *not* a
                        # loss here and is counted as resolved on purpose: the
                        # item does end up linked to this QID; what was dropped
                        # is the older WIKIDATA id it used to hold, which
                        # ``skipped_identities`` reports separately.
                        if linked.item_id == row.item_id:
                            counters["resolved"] += 1
                        else:
                            counters["unlinked"] += 1
                cursor = batch[-1].row_id
                await _write_cursor(session, ANCHOR_KIND, item_type, cursor)
                await session.commit()
            result.skipped_links += collector.count
            result.skipped_identities += collector.identity_count

        result.per_type[item_type] = counters
        result.considered += counters["considered"]
        result.resolved += counters["resolved"]
        result.missing += counters["missing"]
        result.ambiguous += counters["ambiguous"]
        result.unlinked += counters["unlinked"]

    async with session_factory() as session:
        for item_type in types:
            source, _ = ANCHOR_PROPERTIES[item_type]
            result.coverage.append(await get_anchor_coverage(session, item_type, source))
    return result


async def run_relations_pass(
    session_factory: SessionFactory,
    *,
    client: WikidataClient | None = None,
    batch_size: int = WIKIDATA_QID_BATCH,
    budget_minutes: float = 0.0,
    clock=time.monotonic,
) -> RelationsPassResult:
    """Pass B — turn ``P144``/``P4969`` statements into ``item_relations`` edges.

    Both ends are resolved against the QIDs persisted by pass A.  An end the
    catalog does not hold is dropped and added to ``unmatched_ends``; that is
    the common case, not an error — Wikidata knows about far more works than
    this catalog carries.
    """
    client = client or WikidataClient()
    budget = _Budget(budget_minutes, clock=clock)
    result = RelationsPassResult(completed=True)

    async with session_factory() as session:
        cursor = await _read_cursor(session, RELATIONS_KIND, RELATIONS_ITEM_TYPE)

    while True:
        if budget.expired():
            result.completed = False
            logger.warning(
                "wikidata relations: time budget exhausted — stopping at "
                "external_ids.id=%d; re-dispatch to continue",
                cursor,
            )
            break

        async with session_factory() as session:
            batch = await get_anchored_batch(session, cursor, batch_size)
        if not batch:
            async with session_factory() as session:
                await _write_cursor(session, RELATIONS_KIND, RELATIONS_ITEM_TYPE, None)
                await session.commit()
            break

        result.anchored_read += len(batch)
        result.batches += 1
        # A list per QID, not a single row, for the same reason
        # ``resolve_qids_to_items`` returns one: ``uq_external_id`` is scoped
        # per ``item_type``, and Wikidata does sometimes keep a novel and its
        # film on a single entity — so one QID can legitimately anchor both a
        # BOOK and a MOVIE here.  Keeping only the last one would silently
        # attribute one item's statements to the other.
        by_qid: dict[str, list] = {}
        for row in batch:
            by_qid.setdefault(row.qid, []).append(row)
        statements = await client.fetch_relations(list(by_qid))
        result.statements += len(statements)

        async with session_factory() as session:
            targets = await resolve_qids_to_items(
                session, [statement.to_qid for statement in statements]
            )
            writes: list[RelationWrite] = []
            for statement in statements:
                origins = by_qid.get(statement.from_qid)
                if not origins:  # pragma: no cover - the endpoint echoed our VALUES
                    continue
                ends = targets.get(statement.to_qid)
                if not ends:
                    result.unmatched_ends += 1
                    continue
                relation = RELATION_PROPERTIES[statement.property_id]
                for origin in origins:
                    for to_type, to_id in ends:
                        if to_type == origin.item_type and to_id == origin.item_id:
                            result.self_edges += 1
                            continue
                        writes.append(
                            RelationWrite(
                                from_type=origin.item_type,
                                from_id=origin.item_id,
                                to_type=to_type,
                                to_id=to_id,
                                relation=relation,
                                source=SOURCE_WIKIDATA,
                                score=1.0,
                            )
                        )
                        result.per_relation[relation] = result.per_relation.get(relation, 0) + 1
            written = await upsert_item_relations(session, writes)
            cursor = batch[-1].row_id
            await _write_cursor(session, RELATIONS_KIND, RELATIONS_ITEM_TYPE, cursor)
            await session.commit()

        result.created += written.created
        result.updated += written.updated
        result.written += written.written

    return result


def format_coverage_report(coverage: list[AnchorCoverage]) -> list[str]:
    """The per-type anchor coverage report, one printable line per content type.

    Required by the feature's acceptance list ("informe de cobertura del ancla
    por tipo de ítem"). It is a *report*, not a gate: a 5 % anchor on books is
    a fact about how much of Open Library's catalog Wikidata bothers to
    cross-reference, not a failure of this job.
    """
    lines = []
    for row in coverage:
        lines.append(
            f"{row.item_type:<7} {row.anchored:>7} anchored / {row.linked:>7} linked to "
            f"{row.source} ({row.coverage:6.2%}) — catalog holds {row.catalog_items}"
        )
    return lines
