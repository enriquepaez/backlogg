"""The generation pass of the semantic layer (feature 75).

One job, run on the GitHub Actions runner against Neon
(``scripts/generate_embeddings.py``), never on Render and never on the request
path.  It picks a **bounded subset** of the catalog, serialises each item to a
short paragraph, embeds the paragraph with a local multilingual model and
upserts the vector into ``item_embeddings``.

Why a subset, and why the cap is the interesting part
-----------------------------------------------------

Neon's free project is 512 MB and the full catalog is projected at 444-488 MB
(issue #28), so this layer has roughly 80-120 MB to live in.  Every format was
measured against that ceiling and only one fits: ``halfvec(384)`` over ~40.000
items.  The cap is therefore not a throttle that can be raised when convenient
— it is the constraint the whole design is shaped around.  ``docs/operations.md``
carries the measured numbers.

The selection criterion, in one paragraph
-----------------------------------------

The cap is **split into per-type quotas, equally by default**, and each type
fills its quota with its best-signalled items
(``repository._embedding_rank_order``).  Equal shares rather than shares
proportional to catalog size, because feature 80's cross-type quota is its one
non-negotiable rule and it needs *depth in every type*: a proportional split
would hand movies half the budget and leave the smallest type with a few
thousand items, which is the failure this cap was supposed to prevent.  A type
that cannot fill its share hands the remainder back to the others
(``allocate_quotas``), so no capacity is wasted on a type that simply does not
have that many items.

Ranking **within** a type and never across: a TMDB vote count and an IGDB
rating count are different units, and a single global ordering over them would
quietly become a popularity ranking of whichever source inflates hardest.

Idempotent, resumable, and it does not redo work
------------------------------------------------

There is no cursor table.  The candidate list is a deterministic function of
catalog state (a total order, see ``_embedding_rank_order``), and every item
already carrying a vector for the same ``(model, source_hash)`` is skipped
before the model is even asked.  So re-dispatching after a time-budget stop, a
crash or a cancelled workflow recomputes the same list and picks up exactly the
items it had not reached — with no bookkeeping to get out of sync, and with a
second run over an unchanged catalog costing four queries and no inference at
all.

That skip is also what makes the monthly schedule affordable: without it, every
run would re-embed 40.000 items for a handful of edits.
"""

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.config import settings
from backlogg.recommendations.adapters.local_embedder import Embedder
from backlogg.recommendations.repository import (
    EmbeddingSource,
    count_catalog_items,
    load_embedding_sources,
    select_embedding_candidate_ids,
)
from backlogg.shared.item_embeddings import (
    EMBEDDING_ITEM_TYPES,
    EmbeddingWrite,
    StorageReport,
    count_by_item_type,
    get_embedding_column_dim,
    storage_report,
    upsert_item_embeddings,
)

__all__ = [
    "ITEM_TYPES",
    "EmbeddingPassResult",
    "TypeCounters",
    "allocate_quotas",
    "build_source_text",
    "format_quota_plan",
    "format_storage_report",
    "run_embedding_pass",
    "source_hash",
]

logger = logging.getLogger("backlogg.recommendations.embeddings")

#: Fixed order, and it is load-bearing: quota redistribution and remainder
#: hand-out both walk it, so the whole allocation is reproducible.  The same
#: four values live as a frozenset in ``shared.item_embeddings`` — there as the
#: *guard* of the write frontier, here as an *order*; the assertion below keeps
#: the two from drifting apart.
ITEM_TYPES = ("MOVIE", "SERIES", "BOOK", "GAME")
assert set(ITEM_TYPES) == EMBEDDING_ITEM_TYPES

SessionFactory = Callable[[], AsyncSession]


# ── The text that gets embedded ───────────────────────────────────────────────


def build_source_text(source: EmbeddingSource, *, prefix: str = "") -> str:
    """Serialise one item to the paragraph the model sees.

    Title, original title (only when it differs), genres, synopsis — in that
    order, so that whatever the model's window cuts off is the least
    identifying part.

    **The content type is deliberately not in the text.**  Writing "película"
    or "videojuego" into the paragraph would give every item of a type a token
    in common, and the model would dutifully cluster by type — destroying the
    one property this layer exists for, which is that a novel and its
    adaptation land near each other.  The type is a column; it belongs in the
    ``WHERE``, not in the vector.

    Whitespace is collapsed and the parts joined with a single newline so the
    text is **byte-stable**: the hash of this string is what decides whether an
    item is re-embedded, and a synopsis that only gained a trailing space on
    the last sync must not cost 40.000 inferences.
    """
    title = " ".join((source.title or "").split())
    parts = [title] if title else []
    original = " ".join((source.original_title or "").split())
    if original and original.casefold() != title.casefold():
        parts.append(original)
    genres = [genre.strip() for genre in source.genres if genre and genre.strip()]
    if genres:
        parts.append(", ".join(genres))
    overview = " ".join((source.overview or "").split())
    if overview:
        parts.append(overview)
    return prefix + "\n".join(parts)


def source_hash(text: str) -> str:
    """SHA-256 of the serialised text, hex.

    Stored alongside the vector; compared against on the next run together with
    the model name.  Not a cheaper hash because this is not the expensive part
    of anything — the model is — and a collision here means an item silently
    keeps a stale vector forever.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── The quota split ───────────────────────────────────────────────────────────


def allocate_quotas(
    cap: int,
    available: dict[str, int],
    overrides: dict[str, int | None] | None = None,
) -> dict[str, int]:
    """Split ``cap`` across the four types, equally, without wasting capacity.

    An explicit override pins a type's quota (clamped to what it actually has)
    and takes its share off the top.  Everything left is water-filled over the
    remaining types: equal shares, and every time a type saturates — it has
    fewer items than its share — it leaves the pool and its unused share is
    re-split among the rest.  The final remainder (fewer units than types) goes
    one each, in ``ITEM_TYPES`` order, so the result is deterministic rather
    than dependent on dict iteration.

    The guarantee that matters downstream: **no type is starved by another's
    size.**  A cap of 40.000 gives each type 10.000 unless it cannot use them,
    however many millions of rows some other type may have.
    """
    overrides = overrides or {}
    quotas = {item_type: 0 for item_type in ITEM_TYPES}
    budget = max(0, cap)
    pool = []
    for item_type in ITEM_TYPES:
        override = overrides.get(item_type)
        room = max(0, available.get(item_type, 0))
        if override is not None:
            quotas[item_type] = min(max(0, override), room)
            budget -= quotas[item_type]
        else:
            pool.append(item_type)
    budget = max(0, budget)

    while budget > 0 and pool:
        share = budget // len(pool)
        if share == 0:
            # Fewer units left than types: hand them out one by one.
            for item_type in pool:
                if budget <= 0:
                    break
                if quotas[item_type] < available.get(item_type, 0):
                    quotas[item_type] += 1
                    budget -= 1
            break
        progressed = False
        for item_type in list(pool):
            room = available.get(item_type, 0) - quotas[item_type]
            take = min(share, max(0, room))
            if take:
                quotas[item_type] += take
                budget -= take
                progressed = True
            if quotas[item_type] >= available.get(item_type, 0):
                pool.remove(item_type)
        if not progressed:
            break
    return quotas


def format_quota_plan(quotas: dict[str, int], available: dict[str, int]) -> list[str]:
    """One line per type: quota, catalog size, coverage. For the run summary."""
    lines = []
    for item_type in ITEM_TYPES:
        quota = quotas.get(item_type, 0)
        total = available.get(item_type, 0)
        pct = (quota / total * 100) if total else 0.0
        lines.append(
            f"{item_type:<7} quota={quota:>7} of {total:>7} item(s) in catalog "
            f"({pct:5.1f}% covered)"
        )
    return lines


# ── What a run did ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class TypeCounters:
    """Per-type outcome of a run.

    ``selected == skipped_unchanged + embedded + vanished`` always holds, and
    that identity is the point: ``skipped_unchanged`` is the number the "does
    not re-embed what did not change" requirement is read off, and it can only
    be trusted if the buckets partition the selection.
    """

    selected: int = 0
    skipped_unchanged: int = 0
    embedded: int = 0
    created: int = 0
    updated: int = 0
    vanished: int = 0
    without_overview: int = 0


@dataclass(slots=True)
class EmbeddingPassResult:
    """What the whole run did, plus the state it leaves behind."""

    per_type: dict[str, TypeCounters] = field(default_factory=dict)
    quotas: dict[str, int] = field(default_factory=dict)
    available: dict[str, int] = field(default_factory=dict)
    model: str = ""
    batches: int = 0
    completed: bool = True
    storage: StorageReport | None = None
    stored_by_type: dict[str, int] = field(default_factory=dict)

    @property
    def selected(self) -> int:
        return sum(counters.selected for counters in self.per_type.values())

    @property
    def embedded(self) -> int:
        return sum(counters.embedded for counters in self.per_type.values())

    @property
    def skipped_unchanged(self) -> int:
        return sum(counters.skipped_unchanged for counters in self.per_type.values())

    @property
    def created(self) -> int:
        return sum(counters.created for counters in self.per_type.values())

    @property
    def updated(self) -> int:
        return sum(counters.updated for counters in self.per_type.values())

    @property
    def vanished(self) -> int:
        return sum(counters.vanished for counters in self.per_type.values())

    @property
    def types_covered(self) -> int:
        """How many of the four types ended the run with at least one vector."""
        return sum(1 for count in self.stored_by_type.values() if count > 0)


def format_storage_report(report: StorageReport) -> list[str]:
    """The disk measurement, in the shape the acceptance list asks for.

    Data and indexes apart — and the indexes broken down, because
    ``pg_indexes_size`` is the HNSW *plus* ``uq_item_embedding`` plus the
    primary key.  A line labelled ``hnsw index`` over that total would credit
    the ANN index with ~2 MB it does not use, and this report is read during
    the production pre-check, where an error in that direction means believing
    there is more headroom than there is.

    On which of these can actually be traded: the heap is ``rows × 2 bytes ×
    dim`` and shrinks only by dropping rows.  The HNSW looks negotiable through
    ``m`` — fewer graph links, less disk, worse recall — but **measured, that
    lever is nearly empty: ``m=8`` gives back 6 MB out of 45**, because
    pgvector stores the vector itself in every index element and the links are
    the small part.  So the only real lever here is the row count
    (``EMBEDDING_MAX_ITEMS``), which costs coverage rather than quality.
    """
    mb = 1024 * 1024
    return [
        f"rows          {report.rows:>12}",
        f"heap (data)   {report.table_bytes / mb:>9.1f} MB",
        f"toast         {report.toast_bytes / mb:>9.1f} MB",
        f"indexes       {report.index_bytes / mb:>9.1f} MB",
        f"  hnsw (ann)  {report.ann_index_bytes / mb:>9.1f} MB",
        f"  b-trees     {report.btree_index_bytes / mb:>9.1f} MB",
        f"TOTAL         {report.total_bytes / mb:>9.1f} MB",
        f"per item      {report.bytes_per_row:>9.0f} bytes",
    ]


# ── The pass ──────────────────────────────────────────────────────────────────


async def _preflight(db: AsyncSession, embedder: Embedder) -> None:
    """Refuse to start when the model and the column disagree on width.

    ``EMBEDDING_DIM`` is an env var but the migration baked it into the
    ``halfvec`` column, so the two can drift apart silently.  Without this the
    failure surfaces as a Postgres error on the first upsert, after the model
    has been downloaded and a batch inferred — and it says nothing about which
    of the two is wrong.
    """
    column_dim = await get_embedding_column_dim(db)
    if column_dim != settings.EMBEDDING_DIM:
        raise RuntimeError(
            f"item_embeddings.embedding is halfvec({column_dim}) but EMBEDDING_DIM is "
            f"{settings.EMBEDDING_DIM}. The migration bakes the width into the column: "
            f"either restore the variable, or ALTER the column (docs/operations.md)."
        )
    if embedder.dim != settings.EMBEDDING_DIM:
        raise RuntimeError(
            f"{embedder.name} produces {embedder.dim}-dimensional vectors but "
            f"EMBEDDING_DIM is {settings.EMBEDDING_DIM}."
        )


def _chunks(values: Sequence[int], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


async def run_embedding_pass(
    session_factory: SessionFactory,
    embedder: Embedder,
    *,
    item_types: Sequence[str] | None = None,
    max_items: int | None = None,
    batch_size: int | None = None,
    budget_minutes: float | None = None,
    force: bool = False,
) -> EmbeddingPassResult:
    """Generate and persist vectors for the selected subset.

    ``force`` re-embeds even unchanged items; it exists for the one case the
    hash cannot detect, which is a change in how ``build_source_text``
    serialises an item (the stored hash is of the *old* serialisation, and it
    still matches its own text). A model change needs no flag — the model name
    is part of the comparison.

    The time budget is the same contract as the Wikidata job: the run stops
    itself rather than being killed by the Actions timeout, reports
    ``completed=False``, and the next dispatch continues because unchanged
    items are skipped.
    """
    types = tuple(item_types) if item_types else ITEM_TYPES
    unknown = sorted(set(types) - set(ITEM_TYPES))
    if unknown:
        raise ValueError(f"run_embedding_pass: unknown item type(s) {unknown}")
    cap = settings.EMBEDDING_MAX_ITEMS if max_items is None else max_items
    size = batch_size or settings.EMBEDDING_BATCH_SIZE
    budget = settings.EMBEDDING_TIME_BUDGET_MINUTES if budget_minutes is None else budget_minutes
    deadline = time.monotonic() + budget * 60 if budget and budget > 0 else None

    result = EmbeddingPassResult(model=embedder.name)

    async with session_factory() as db:
        await _preflight(db, embedder)
        available = {
            item_type: await count_catalog_items(db, item_type) for item_type in ITEM_TYPES
        }
    overrides: dict[str, int | None] = {
        "MOVIE": settings.EMBEDDING_MAX_ITEMS_MOVIES,
        "SERIES": settings.EMBEDDING_MAX_ITEMS_SERIES,
        "BOOK": settings.EMBEDDING_MAX_ITEMS_BOOKS,
        "GAME": settings.EMBEDDING_MAX_ITEMS_GAMES,
    }
    # A run restricted to some types keeps the *full* allocation and then only
    # walks the requested ones: re-running one type must not silently hand it
    # the other three's budget and blow past the cap.
    quotas = allocate_quotas(cap, available, overrides)
    result.quotas = quotas
    result.available = available

    for item_type in types:
        counters = result.per_type.setdefault(item_type, TypeCounters())
        async with session_factory() as db:
            candidate_ids = await select_embedding_candidate_ids(
                db, item_type, quotas.get(item_type, 0)
            )
        counters.selected = len(candidate_ids)
        logger.info(
            "embeddings: %s — %d candidate(s) selected (quota %d, catalog %d)",
            item_type,
            counters.selected,
            quotas.get(item_type, 0),
            available.get(item_type, 0),
        )

        for batch_ids in _chunks(candidate_ids, size):
            if deadline is not None and time.monotonic() >= deadline:
                result.completed = False
                logger.warning(
                    "embeddings: time budget of %.1f min reached — stopping with the "
                    "subset partially covered. Re-dispatch to continue: unchanged items "
                    "are skipped, so the next run resumes where this one stopped.",
                    budget,
                )
                break
            result.batches += 1
            async with session_factory() as db:
                sources = await load_embedding_sources(db, item_type, batch_ids)
                counters.vanished += len(batch_ids) - len(sources)
                pending: list[tuple[EmbeddingSource, str]] = []
                for source in sources:
                    if not (source.overview or "").strip():
                        counters.without_overview += 1
                    text = build_source_text(source, prefix=settings.EMBEDDING_TEXT_PREFIX)
                    digest = source_hash(text)
                    unchanged = (
                        source.stored_hash == digest and source.stored_model == embedder.name
                    )
                    if unchanged and not force:
                        counters.skipped_unchanged += 1
                        continue
                    pending.append((source, text))
                if not pending:
                    continue
                # Inference is CPU-bound and synchronous; off the event loop so
                # the connection this session holds is not blocked for the
                # seconds a batch takes.
                vectors = await asyncio.to_thread(
                    embedder.embed, [text for _source, text in pending]
                )
                if len(vectors) != len(pending):
                    raise RuntimeError(
                        f"{embedder.name} returned {len(vectors)} vector(s) for "
                        f"{len(pending)} text(s)"
                    )
                writes = [
                    EmbeddingWrite(
                        item_type=source.item_type,
                        item_id=source.item_id,
                        embedding=vector,
                        model=embedder.name,
                        source_hash=source_hash(text),
                    )
                    for (source, text), vector in zip(pending, vectors, strict=True)
                ]
                upsert = await upsert_item_embeddings(db, writes)
                await db.commit()
            counters.embedded += len(writes)
            counters.created += upsert.created
            counters.updated += upsert.updated
        if not result.completed:
            break

    async with session_factory() as db:
        result.stored_by_type = await count_by_item_type(db)
        result.storage = await storage_report(db)
    return result
