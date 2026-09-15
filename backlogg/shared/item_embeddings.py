"""``item_embeddings`` — one semantic vector per catalog item, polymorphic.

The *Capa 1 — Semántica* of ``docs/recommendations-plan.md``: every item has a
title, genres and a synopsis whatever its type, so serialising that to a
paragraph and embedding it puts movies, series, books and games in **one**
vector space.  Cosine there crosses types by construction, which is the whole
reason this layer exists — it is the bridge feature 80 ranks on top of.

One table, not a column per content table
-----------------------------------------

Same polymorphic shape as ``external_ids``, ``credits`` and ``item_relations``:
``(item_type, item_id)`` with no foreign key, integrity owned by the
application (``docs/conventions.md``).  Four ``embedding`` columns would mean
four HNSW indexes, and a cross-type nearest-neighbour read would have to query
all four and merge — which is precisely the operation this layer is supposed to
make free.

``halfvec``, not ``vector``
---------------------------

Disk is the binding constraint, not compute: Neon's free project is 512 MB and
``docs/operations.md`` measures the full catalog at 444-488 MB, leaving roughly
80-120 MB.  ``halfvec`` stores each component as an IEEE half (2 bytes) instead
of a float32 (4), halving both the table and the HNSW index for a quantisation
error far below the noise floor of a 384-dimensional sentence embedding.  The
alternative saving — truncating the vector to 256 dimensions — was rejected in
``progress/current.md`` §2.1: the model is not Matryoshka, so a truncated
vector degrades with no guarantee, whereas ``halfvec`` does not touch what the
model produced.  When more room is needed the **subset** shrinks (coverage),
never the dimensionality (quality per item).

No new runtime dependency
-------------------------

Production does not need ``pgvector``'s Python package (nor the ``numpy`` it
pulls in).  pgvector ships casts ``double precision[] -> halfvec`` and
``halfvec -> real[]``, and asyncpg speaks both array types natively, so
``HalfVec`` below binds a plain ``list[float]`` through those casts.  The API
image therefore gains **zero** dependencies from this feature — consistent with
the harder rule that the *model* never enters it either (see
``backlogg/recommendations/adapters/local_embedder.py``).

Writes happen in the ingestion pipeline, reads on the request path
------------------------------------------------------------------

Nothing here is called while serving a request except the two read helpers, and
neither of them runs a model: the anchor vector of a "more like this" query is
the row the catalog already stores, so the whole query is a single ANN lookup
against the HNSW index.  ``upsert_item_embeddings`` is called only from the
GitHub Actions job (``scripts/generate_embeddings.py``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    func,
    literal_column,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from backlogg.core.config import settings
from backlogg.core.database import Base

__all__ = [
    "EMBEDDING_ITEM_TYPES",
    "EmbeddingWrite",
    "HalfVec",
    "ItemEmbedding",
    "SimilarItem",
    "StorageReport",
    "UpsertResult",
    "count_item_embeddings",
    "count_by_item_type",
    "get_embedding_column_dim",
    "get_item_embedding",
    "get_similar_by_item",
    "get_similar_by_vector",
    "storage_report",
    "upsert_item_embeddings",
]

#: The four content types that can carry an embedding.  Kept here and not
#: imported from the recommendations domain because this module is the write
#: frontier: an unknown ``item_type`` is rejected before it reaches the table.
EMBEDDING_ITEM_TYPES = frozenset({"MOVIE", "SERIES", "BOOK", "GAME"})


class HalfVec(UserDefinedType):
    """pgvector's ``halfvec(n)`` as a SQLAlchemy type, over plain Python lists.

    Binding goes out as ``CAST(CAST($n AS FLOAT[]) AS halfvec(d))`` and reading
    comes back as ``CAST(col AS REAL[])``.  The double cast is not decoration:
    asyncpg refuses to send a parameter whose Postgres type it does not know,
    and ``CAST($n AS halfvec)`` alone would make the server infer the parameter
    *as* ``halfvec``.  Routing through ``float8[]`` — a type asyncpg has a
    native codec for — sidesteps the whole problem without registering a codec
    on every connection.  The read direction uses ``real[]`` because that is
    the only array cast pgvector declares **out** of ``halfvec``.
    """

    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        return f"halfvec({self.dim})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            return [float(component) for component in value]

        return process

    def bind_expression(self, bindvalue):
        return sa.cast(sa.cast(bindvalue, ARRAY(sa.Float)), self)

    def column_expression(self, col):
        return sa.cast(col, ARRAY(sa.REAL))

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            return [float(component) for component in value]

        return process


class ItemEmbedding(Base):
    __tablename__ = "item_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(HalfVec(settings.EMBEDDING_DIM), nullable=False)
    # Which model produced the vector.  Part of the "do not re-embed what did
    # not change" test together with ``source_hash``: a vector produced by
    # another model lives in another space and has to be redone even though the
    # text is identical.
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    # SHA-256 of the exact serialised source text.  The single reason the job
    # can run monthly over a 40.000-item subset in minutes instead of hours.
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("item_type", "item_id", name="uq_item_embedding"),
        # The ANN index the whole layer exists for.  Declared here so
        # ``Base.metadata`` matches the database; the migration creates the
        # real one (Alembic cannot express an operator class inline).
        Index(
            "idx_item_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
        ),
    )


@dataclass(frozen=True, slots=True)
class EmbeddingWrite:
    """One vector to persist.  Plain data — the caller needs no ORM instance."""

    item_type: str
    item_id: int
    embedding: Sequence[float]
    model: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """How many vectors a write created and how many it refreshed.

    Split for the same reason as ``item_relations.UpsertResult``: idempotency
    has to be observable.  A second pass over an unchanged catalog must report
    ``created == 0`` **and** ``updated == 0``, because the job skips unchanged
    items before it gets this far.
    """

    created: int = 0
    updated: int = 0

    @property
    def written(self) -> int:
        return self.created + self.updated


@dataclass(frozen=True, slots=True)
class SimilarItem:
    """One neighbour, with cosine **similarity** in ``[-1, 1]`` (1 = identical)."""

    item_type: str
    item_id: int
    score: float


@dataclass(frozen=True, slots=True)
class StorageReport:
    """What the layer actually costs on disk, data and indexes apart.

    Exists because the acceptance list of feature 75 asks for a real
    measurement, not an estimate, and because the budget it is measured against
    (~80-120 MB of Neon free headroom) is tight enough that an estimate off by
    a third would be the difference between fitting and breaking production.

    ``index_bytes`` is **every** index (``pg_indexes_size``), and
    ``ann_index_bytes`` is the HNSW alone.  They are two fields and not one
    because the difference is ~2 MB of b-trees, and an operator reading this
    during the production pre-check would otherwise credit the ANN index with
    space it does not use — an error that points the wrong way, towards
    believing there is more headroom than there is.
    """

    rows: int
    table_bytes: int
    index_bytes: int
    ann_index_bytes: int
    toast_bytes: int

    @property
    def btree_index_bytes(self) -> int:
        """``uq_item_embedding`` + the primary key — everything but the HNSW."""
        return self.index_bytes - self.ann_index_bytes

    @property
    def total_bytes(self) -> int:
        return self.table_bytes + self.index_bytes + self.toast_bytes

    @property
    def bytes_per_row(self) -> float:
        return self.total_bytes / self.rows if self.rows else 0.0


async def upsert_item_embeddings(db: AsyncSession, rows: Sequence[EmbeddingWrite]) -> UpsertResult:
    """Insert or refresh ``rows`` in one statement, keyed by ``uq_item_embedding``.

    Idempotent by construction: re-offering a vector for an item that already
    has one overwrites it instead of raising or duplicating, which is what lets
    the job be re-dispatched at any point without bookkeeping.

    An unknown ``item_type`` raises, following ``upsert_item_relations``: the
    column is a bare ``VARCHAR(20)`` with no CHECK behind it, so a typo would
    insert happily and the vectors would simply never be found again by any
    reader that filters by type — the silent-loss failure mode of issues #7,
    #15 and #20.  A vector whose length disagrees with the column raises too,
    and for a blunter reason: Postgres would reject the whole batch with
    ``expected N dimensions, not M``, and the job would lose every item in it
    because one was malformed.
    """
    unknown = sorted({row.item_type for row in rows} - EMBEDDING_ITEM_TYPES)
    if unknown:
        raise ValueError(
            f"upsert_item_embeddings: unknown item_type(s) {unknown} — the embedding "
            f"layer covers {sorted(EMBEDDING_ITEM_TYPES)}"
        )
    expected_dim = settings.EMBEDDING_DIM
    wrong = sorted(
        {
            (row.item_type, row.item_id, len(row.embedding))
            for row in rows
            if len(row.embedding) != expected_dim
        }
    )
    if wrong:
        raise ValueError(
            f"upsert_item_embeddings: {len(wrong)} vector(s) do not have "
            f"EMBEDDING_DIM={expected_dim} components (first: {wrong[0]})"
        )
    # Collapse duplicates inside the batch: Postgres refuses an ON CONFLICT
    # whose command touches the same key twice ("cannot affect row a second
    # time"), and the caller builds batches from a candidate list that a
    # future selection rule could legitimately emit twice.
    deduped: dict[tuple[str, int], EmbeddingWrite] = {}
    for row in rows:
        deduped[(row.item_type, row.item_id)] = row
    if not deduped:
        return UpsertResult()

    base = insert(ItemEmbedding).values(
        [
            {
                "item_type": row.item_type,
                "item_id": row.item_id,
                "embedding": list(row.embedding),
                "model": row.model,
                "source_hash": row.source_hash,
            }
            for row in deduped.values()
        ]
    )
    stmt = base.on_conflict_do_update(
        constraint="uq_item_embedding",
        set_={
            "embedding": base.excluded.embedding,
            "model": base.excluded.model,
            "source_hash": base.excluded.source_hash,
            "updated_at": func.now(),
        },
    ).returning(literal_column("(xmax = 0)", type_=Boolean).label("inserted"))
    # ``xmax = 0`` is the canonical Postgres discriminant for "this RETURNING
    # row came out of the INSERT arm" — same trick as upsert_item_relations.
    result = await db.execute(stmt)
    created = 0
    updated = 0
    for (inserted,) in result.all():
        if inserted:
            created += 1
        else:
            updated += 1
    await db.flush()
    return UpsertResult(created=created, updated=updated)


async def get_item_embedding(
    db: AsyncSession, item_type: str, item_id: int
) -> ItemEmbedding | None:
    """The stored row for one item, or ``None`` if it is outside the subset."""
    result = await db.execute(
        select(ItemEmbedding).where(
            ItemEmbedding.item_type == item_type, ItemEmbedding.item_id == item_id
        )
    )
    return result.scalar_one_or_none()


def _similarity(distance):
    """Cosine *similarity* from pgvector's cosine **distance** (``<=>``)."""
    return (sa.literal(1.0) - distance).label("score")


async def get_similar_by_vector(
    db: AsyncSession,
    embedding: Sequence[float],
    *,
    limit: int = 20,
    item_types: Sequence[str] | None = None,
    exclude: tuple[str, int] | None = None,
) -> list[SimilarItem]:
    """Nearest neighbours of an arbitrary vector, closest first.

    ``ORDER BY embedding <=> :query LIMIT n`` is the exact shape the HNSW index
    answers; any other ordering (or an ordering wrapped in arithmetic) falls
    back to a sequential scan, which is why the similarity conversion happens
    in the select list and never in ``ORDER BY``.

    **A narrowed query can return fewer than ``limit`` rows.**  ``item_types``
    and ``exclude`` are applied as a filter *after* the index walk (verified in
    the plan: ``Index Scan using idx_item_embeddings_hnsw`` + ``Filter``), so
    asking for 20 books among mostly-games neighbours can come back short even
    though 20 books exist.  That is inherent to a filtered ANN, not a bug here;
    a caller that needs a full page raises ``hnsw.ef_search`` or over-fetches.
    """
    query = sa.bindparam(
        "query_vector", value=list(embedding), type_=HalfVec(settings.EMBEDDING_DIM)
    )
    distance = ItemEmbedding.embedding.op("<=>", return_type=sa.Float)(query)
    stmt = select(ItemEmbedding.item_type, ItemEmbedding.item_id, _similarity(distance))
    if item_types:
        stmt = stmt.where(ItemEmbedding.item_type.in_(list(item_types)))
    if exclude is not None:
        excluded_type, excluded_id = exclude
        stmt = stmt.where(
            sa.not_(
                sa.and_(
                    ItemEmbedding.item_type == excluded_type,
                    ItemEmbedding.item_id == excluded_id,
                )
            )
        )
    stmt = stmt.order_by(distance).limit(limit)
    result = await db.execute(stmt)
    return [
        SimilarItem(item_type=row.item_type, item_id=row.item_id, score=float(row.score))
        for row in result.all()
    ]


async def get_similar_by_item(
    db: AsyncSession,
    item_type: str,
    item_id: int,
    *,
    limit: int = 20,
    item_types: Sequence[str] | None = None,
    ef_search: int | None = None,
) -> list[SimilarItem]:
    """Nearest neighbours of an item **that is already embedded**.

    The anchor vector is read as a scalar subquery rather than round-tripped
    through Python: no vector ever crosses the wire, the whole thing is one
    statement, and — the point of the layer — the request path runs no model.
    An item outside the subset yields an empty list, never an error: the subset
    is bounded on purpose (see the module docstring) and "not embedded" is an
    ordinary, expected state that feature 80 has to fall back from.

    ``ef_search`` widens pgvector's HNSW candidate window (``SET LOCAL
    hnsw.ef_search``) for this statement only.  It exists because ``item_types``
    is a **post-filter**, applied to whatever the index walk already produced:
    with the default window of 40, asking for the nearest books of a game in an
    index that is 94% games returns **nothing at all**, not "fewer than asked".
    That is not hypothetical — it is what feature 80's cross-type quota hit on
    the real development catalog (33.062 games out of 35.215 vectors), where
    the quota silently reserved slots it could never fill.  Widening the window
    is pgvector's own answer to a filtered ANN; the cost is a longer walk in
    the same index, paid only by the caller that asks for it.
    """
    if ef_search is not None:
        # SET LOCAL: scoped to the surrounding transaction, which for a request
        # is the request. A session-wide SET would make one endpoint's recall
        # setting leak into every other query on the pooled connection —
        # verified not to survive a COMMIT, a ROLLBACK or the recycling of the
        # connection.
        #
        # It does stay in force for the rest of *this* transaction, i.e. for
        # whatever the caller runs next. That is harmless rather than merely
        # tolerable: no other statement on the request path touches the HNSW
        # index (feature 80's follow-up read hydrates rows by primary key), so
        # the setting has nothing left to affect.
        await db.execute(sa.text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
    anchor = (
        select(ItemEmbedding.embedding)
        .where(ItemEmbedding.item_type == item_type, ItemEmbedding.item_id == item_id)
        .scalar_subquery()
    )
    distance = ItemEmbedding.embedding.op("<=>", return_type=sa.Float)(anchor)
    stmt = select(ItemEmbedding.item_type, ItemEmbedding.item_id, _similarity(distance)).where(
        sa.not_(
            sa.and_(
                ItemEmbedding.item_type == item_type,
                ItemEmbedding.item_id == item_id,
            )
        )
    )
    if item_types:
        stmt = stmt.where(ItemEmbedding.item_type.in_(list(item_types)))
    stmt = stmt.order_by(distance).limit(limit)
    result = await db.execute(stmt)
    return [
        SimilarItem(item_type=row.item_type, item_id=row.item_id, score=float(row.score))
        for row in result.all()
        if row.score is not None
    ]


async def count_item_embeddings(db: AsyncSession, *, item_type: str | None = None) -> int:
    """How many vectors are persisted, optionally narrowed to one type."""
    stmt = select(func.count()).select_from(ItemEmbedding)
    if item_type is not None:
        stmt = stmt.where(ItemEmbedding.item_type == item_type)
    return int((await db.execute(stmt)).scalar_one())


async def count_by_item_type(db: AsyncSession) -> dict[str, int]:
    """Rows per content type — the cross-type coverage check, in one query."""
    result = await db.execute(
        select(ItemEmbedding.item_type, func.count()).group_by(ItemEmbedding.item_type)
    )
    return {row[0]: int(row[1]) for row in result.all()}


async def storage_report(db: AsyncSession) -> StorageReport:
    """Measure what ``item_embeddings`` costs on disk, right now.

    Heap, TOAST, HNSW and b-trees are reported apart because they grow for
    different reasons — and the measurement settled which of them can actually
    be traded, correcting the assumption this docstring used to carry.

    The intuition was that the heap is fixed (``rows × 2 bytes × dim``) while
    the HNSW index is ``rows × m × (link size)`` and could therefore be rebuilt
    cheaper with a smaller ``m``, paying in recall.  **Measured on 40.000 rows,
    that lever is nearly empty: ``m=8`` gives back 6 MB out of 45.**  pgvector
    stores the *vector itself* in every HNSW element, so the graph links — the
    only part ``m`` governs — are a small fraction of the index.

    Which leaves one real lever on disk, and it is neither the format nor the
    index parameters: **the number of rows** (``EMBEDDING_MAX_ITEMS``).  That
    is why the cap, and not quality, is what shrinks when the budget does.
    """
    row = (
        await db.execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM item_embeddings) AS rows,
                    pg_table_size('item_embeddings')
                        - COALESCE(pg_total_relation_size(reltoastrelid), 0) AS table_bytes,
                    pg_indexes_size('item_embeddings') AS index_bytes,
                    -- The ANN index alone. COALESCE over to_regclass so a
                    -- report taken between the DROP and the CREATE of an index
                    -- rebuild (docs/operations.md, changing EMBEDDING_DIM)
                    -- reads 0 instead of raising.
                    COALESCE(
                        pg_relation_size(to_regclass('idx_item_embeddings_hnsw')), 0
                    ) AS ann_index_bytes,
                    COALESCE(pg_total_relation_size(reltoastrelid), 0) AS toast_bytes
                FROM pg_class
                WHERE oid = 'item_embeddings'::regclass
                """
            )
        )
    ).one()
    return StorageReport(
        rows=int(row.rows),
        table_bytes=int(row.table_bytes),
        index_bytes=int(row.index_bytes),
        ann_index_bytes=int(row.ann_index_bytes),
        toast_bytes=int(row.toast_bytes),
    )


async def get_embedding_column_dim(db: AsyncSession) -> int:
    """The dimensionality the **database** column was created with.

    ``EMBEDDING_DIM`` is an env var, and the migration bakes its value into the
    column type, so the two can drift: change the variable after migrating and
    every write fails deep inside Postgres with ``expected N dimensions``.  The
    job calls this on startup to fail with a sentence that says what to do
    instead.  ``atttypmod`` of a ``halfvec`` column is the dimension itself.
    """
    return int(
        (
            await db.execute(
                sa.text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'item_embeddings'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar_one()
    )
