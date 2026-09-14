"""``item_relations`` — the polymorphic edge table between catalog items.

The shape comes from ``docs/recommendations-plan.md`` («Capa 2 — Conocimiento:
adaptaciones vía Wikidata»), and it is shared on purpose: feature 79 fills it
with the *knowledge* layer (Wikidata's explicit ``P144``/``P4969`` statements
between a novel, its film and its game) and feature 83 will fill the very same
table with the *behaviour* layer (item-item co-occurrence over user libraries,
``relation='COOCCURRENCE'``, ``source='INTERNAL'``).

Why one table and not two
-------------------------

The consumer is a single ranker that has to merge candidates from several
layers, weigh them and cut a top-N.  With one table per layer that merge is a
UNION whose arms change every time a layer is added; with one table it is a
filter on ``source``/``relation``.  The layers differ in *how the edge was
derived*, not in *what an edge is* — both are "item A relates to item B with
strength S" — and that is exactly what a ``source`` column is for.

**The consequence, and it is a hard rule: no wide ``DELETE``.**  A recompute
that wanted to start clean and ran ``DELETE FROM item_relations`` would take
the other layer with it, and the Wikidata half costs a full SPARQL pass to
rebuild while the co-occurrence half costs a batch job over every library in
the database.  Every write here is an **upsert**, and any deletion a future
layer needs must carry ``WHERE source = '<its own>'``.  ``delete_relations_by_source``
below exists so that rule has one implementation instead of four call sites
each remembering to add the predicate.

Direction is not symmetric, and is not normalised
-------------------------------------------------

An edge is stored exactly as the source asserts it, once, in that direction:

======================= ============================================
``relation``            meaning of ``(from, to)``
======================= ============================================
``ADAPTATION``          *from* is based on *to* (Wikidata ``P144``):
                        the film -> the novel it adapts
``DERIVATIVE``          *to* is derived from *from* (``P4969``):
                        the novel -> the game spun off it
``COOCCURRENCE``        symmetric by construction (feature 83); it
                        still gets one row per ordered pair so the
                        "given this item, its neighbours" read is a
                        single index lookup on the ``from`` side
======================= ============================================

Writing the mirror edge of ``ADAPTATION``/``DERIVATIVE`` was rejected: it
doubles the rows, and the two properties are already declared inverses in
Wikidata, so a well-curated pair *arrives* in both directions and would be
stored twice over.  Readers that want "everything related to X" query both
sides (``get_relations_for_item`` does exactly that).

No foreign keys — the reference is polymorphic, like ``external_ids`` and
``credits``, and integrity is the application's job (``docs/conventions.md``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    String,
    UniqueConstraint,
    delete,
    func,
    literal_column,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

__all__ = [
    "RELATIONS",
    "RELATION_ADAPTATION",
    "RELATION_COOCCURRENCE",
    "RELATION_DERIVATIVE",
    "SOURCE_INTERNAL",
    "SOURCE_WIKIDATA",
    "ItemRelation",
    "RelationRow",
    "RelationWrite",
    "UpsertResult",
    "count_item_relations",
    "delete_relations_by_source",
    "get_relations_for_item",
    "upsert_item_relations",
]

#: ``from`` is based on ``to`` — Wikidata ``P144`` (*based on*).
RELATION_ADAPTATION = "ADAPTATION"
#: ``to`` is derived from ``from`` — Wikidata ``P4969`` (*derivative work*).
RELATION_DERIVATIVE = "DERIVATIVE"
#: Reserved for feature 83; no writer emits it yet.
RELATION_COOCCURRENCE = "COOCCURRENCE"

#: The closed vocabulary of ``item_relations.relation``.  ``upsert_item_relations``
#: refuses anything outside it — see the note on its docstring for why this is a
#: guard and not decoration.
RELATIONS = frozenset({RELATION_ADAPTATION, RELATION_DERIVATIVE, RELATION_COOCCURRENCE})

SOURCE_WIKIDATA = "WIKIDATA"
SOURCE_INTERNAL = "INTERNAL"


class ItemRelation(Base):
    __tablename__ = "item_relations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    from_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    to_type: Mapped[str] = mapped_column(String(20), nullable=False)
    to_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    relation: Mapped[str] = mapped_column(String(20), nullable=False)
    # Confidence/strength of the edge, in [0, 1].  Wikidata writes 1.0: an
    # explicit ``P144`` statement is an assertion, not an estimate.  Feature 83
    # will write a real cosine here, which is why the column exists already —
    # adding it later would mean a migration over a table with rows in it.
    score: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "from_type",
            "from_id",
            "to_type",
            "to_id",
            "relation",
            "source",
            name="uq_item_relation",
        ),
        # An item related to itself is always a bug — a Wikidata statement
        # pointing at its own entity, or two catalog rows that turned out to be
        # the same item.  Cheap to enforce, and it would otherwise show up as a
        # recommendation of the page you are already on.
        CheckConstraint(
            "NOT (from_type = to_type AND from_id = to_id)",
            name="ck_item_relation_not_self",
        ),
        # Reverse lookup only.  The forward one — "given this item, what does
        # it point at" — is already served by the leading columns of
        # ``uq_item_relation``; a second index on the same prefix would cost
        # writes and buy nothing.
        Index("idx_item_relations_to", "to_type", "to_id", "relation"),
    )


@dataclass(frozen=True, slots=True)
class RelationWrite:
    """One edge to persist.  Plain data so the caller needs no ORM instance."""

    from_type: str
    from_id: int
    to_type: str
    to_id: int
    relation: str
    source: str
    score: float = 1.0


@dataclass(frozen=True, slots=True)
class RelationRow:
    """One persisted edge, as read back by ``get_relations_for_item``."""

    from_type: str
    from_id: int
    to_type: str
    to_id: int
    relation: str
    source: str
    score: float


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """How many edges a write created and how many it refreshed.

    The split is what makes idempotency observable: a second identical pass
    must report ``created == 0``, and a job that keeps creating rows month
    after month is resolving its ends differently each time.
    """

    created: int = 0
    updated: int = 0

    @property
    def written(self) -> int:
        return self.created + self.updated


async def upsert_item_relations(db: AsyncSession, rows: Sequence[RelationWrite]) -> UpsertResult:
    """Insert or refresh ``rows`` in one statement, keyed by ``uq_item_relation``.

    Idempotent by construction: re-offering an edge that exists updates its
    ``score`` and ``updated_at`` instead of raising or duplicating, which is
    what lets the whole job be re-dispatched at any point.

    Self-edges are dropped here rather than left to the CHECK constraint: they
    are a data condition the callers can legitimately meet (Wikidata has a
    handful of entities pointing at themselves) and one of them would otherwise
    abort the entire batch.  Duplicates *inside* ``rows`` are collapsed too —
    Postgres refuses an ``ON CONFLICT`` whose command touches the same key
    twice ("cannot affect row a second time"), and a single SPARQL page can
    easily carry the same pair from two statements.

    **An unknown ``relation`` raises.**  The column is a bare ``VARCHAR(20)``
    with no CHECK behind it, so a typo — ``COOCURRENCE`` for ``COOCCURRENCE`` —
    would insert perfectly happily and the ranker would simply never find those
    rows again: a silent loss of exactly the kind that chained issues #7, #15
    and #20 in this project, each found months later by accident.  Refusing at
    the single write path costs one ``if`` and follows the precedent of
    ``backlogg/shared/codes.py``, which raises on an unknown role rather than
    coercing it.  ``source`` is deliberately *not* validated the same way: it
    is a provenance label, and a wrong one is visible the moment anybody
    filters by it, whereas a wrong ``relation`` hides inside a layer that is
    already expected to be sparse.
    """
    unknown = sorted({row.relation for row in rows} - RELATIONS)
    if unknown:
        raise ValueError(
            f"upsert_item_relations: unknown relation(s) {unknown} — add them to "
            f"RELATIONS in backlogg/shared/item_relations.py before persisting them "
            f"(known: {sorted(RELATIONS)})"
        )
    deduped: dict[tuple[str, int, str, int, str, str], RelationWrite] = {}
    for row in rows:
        if row.from_type == row.to_type and row.from_id == row.to_id:
            continue
        key = (row.from_type, row.from_id, row.to_type, row.to_id, row.relation, row.source)
        deduped[key] = row
    if not deduped:
        return UpsertResult()

    base = insert(ItemRelation).values(
        [
            {
                "from_type": row.from_type,
                "from_id": row.from_id,
                "to_type": row.to_type,
                "to_id": row.to_id,
                "relation": row.relation,
                "source": row.source,
                "score": row.score,
            }
            for row in deduped.values()
        ]
    )
    stmt = base.on_conflict_do_update(
        constraint="uq_item_relation",
        set_={"score": base.excluded.score, "updated_at": func.now()},
    ).returning(literal_column("(xmax = 0)", type_=Boolean).label("inserted"))
    # ``xmax = 0`` is the canonical Postgres discriminant for "this RETURNING
    # row came out of the INSERT arm", and the only one available: an
    # ``ON CONFLICT DO UPDATE`` returns both arms indistinguishably otherwise.
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


async def get_relations_for_item(
    db: AsyncSession,
    item_type: str,
    item_id: int,
    *,
    source: str | None = None,
    relation: str | None = None,
) -> list[RelationRow]:
    """Every edge touching this item, on either side.

    Both sides because direction encodes *which end adapts which* and not
    relevance: someone on the page of the novel wants the film as much as
    someone on the page of the film wants the novel, and only one of the two
    rows exists (see the module docstring on why the mirror is not stored).
    """
    conditions = or_(
        (ItemRelation.from_type == item_type) & (ItemRelation.from_id == item_id),
        (ItemRelation.to_type == item_type) & (ItemRelation.to_id == item_id),
    )
    stmt = select(ItemRelation).where(conditions)
    if source is not None:
        stmt = stmt.where(ItemRelation.source == source)
    if relation is not None:
        stmt = stmt.where(ItemRelation.relation == relation)
    stmt = stmt.order_by(ItemRelation.score.desc(), ItemRelation.id.asc())
    result = await db.execute(stmt)
    return [
        RelationRow(
            from_type=row.from_type,
            from_id=row.from_id,
            to_type=row.to_type,
            to_id=row.to_id,
            relation=row.relation,
            source=row.source,
            score=row.score,
        )
        for row in result.scalars().all()
    ]


async def count_item_relations(
    db: AsyncSession, *, source: str | None = None, relation: str | None = None
) -> int:
    """How many edges are persisted, optionally narrowed to one layer."""
    stmt = select(func.count()).select_from(ItemRelation)
    if source is not None:
        stmt = stmt.where(ItemRelation.source == source)
    if relation is not None:
        stmt = stmt.where(ItemRelation.relation == relation)
    return int((await db.execute(stmt)).scalar_one())


async def delete_relations_by_source(db: AsyncSession, source: str) -> int:
    """Remove every edge of **one** source, and only of that source.

    The single implementation of the hard rule in the module docstring: the
    ``WHERE source`` predicate is not optional and cannot be forgotten at a
    call site, because there is no call site that builds the DELETE itself.
    Nothing in feature 79 calls this — the job is an upsert — but a layer that
    needs to start clean has to have somewhere safe to do it.
    """
    result = await db.execute(delete(ItemRelation).where(ItemRelation.source == source))
    await db.flush()
    return int(result.rowcount or 0)
