"""Feature 79 — the ``item_relations`` table and its helpers, against real Postgres.

The table is created by migration ``0041`` and **shared with feature 83**, so
what is under test here is mostly the machinery that keeps two layers able to
live in it at once:

- the unique key carries ``source`` and ``relation``, so the knowledge layer
  and the behaviour layer never overwrite each other's score for the same pair,
  and ``P144``/``P4969`` (declared inverses in Wikidata) can both be stored;
- the write is an upsert: re-offering an edge refreshes it instead of raising
  or duplicating, which is what makes the monthly job re-runnable;
- duplicates *inside* one batch are collapsed, because Postgres refuses an
  ``ON CONFLICT`` that touches the same key twice;
- a self-edge is refused by a CHECK constraint and dropped by the writer
  before it can abort a whole batch;
- the read returns edges on **both** sides of the item, because direction
  encodes which end adapts which and only one of the two rows is stored;
- deletion exists only scoped to one source — the rule that protects the other
  layer's rows;
- a ``relation`` outside the closed vocabulary is refused by the writer, and
  the whole batch with it.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from backlogg.movies.models import Movie
from backlogg.shared.item_relations import (
    RELATION_ADAPTATION,
    RELATION_COOCCURRENCE,
    RELATION_DERIVATIVE,
    RELATIONS,
    SOURCE_INTERNAL,
    SOURCE_WIKIDATA,
    ItemRelation,
    RelationWrite,
    count_item_relations,
    delete_relations_by_source,
    get_relations_for_item,
    upsert_item_relations,
)

pytestmark = pytest.mark.asyncio


def _edge(from_id: int, to_id: int, relation: str, source: str, score: float = 1.0):
    return RelationWrite(
        from_type="MOVIE",
        from_id=from_id,
        to_type="BOOK",
        to_id=to_id,
        relation=relation,
        source=source,
        score=score,
    )


async def test_the_same_pair_can_hold_one_edge_per_relation_and_source(db):
    """Four rows for one pair, and that is the point of the key's shape."""
    rows = [
        _edge(1, 2, RELATION_ADAPTATION, SOURCE_WIKIDATA),
        _edge(1, 2, RELATION_DERIVATIVE, SOURCE_WIKIDATA),
        _edge(1, 2, RELATION_COOCCURRENCE, SOURCE_INTERNAL, score=0.7),
        _edge(1, 2, RELATION_ADAPTATION, SOURCE_INTERNAL, score=0.3),
    ]
    result = await upsert_item_relations(db, rows)
    assert result.created == 4
    assert await count_item_relations(db) == 4
    assert await count_item_relations(db, source=SOURCE_WIKIDATA) == 2
    assert await count_item_relations(db, relation=RELATION_COOCCURRENCE) == 1


async def test_reoffering_an_edge_refreshes_it_instead_of_duplicating(db):
    first = await upsert_item_relations(db, [_edge(3, 4, RELATION_ADAPTATION, SOURCE_WIKIDATA)])
    assert first.created == 1 and first.updated == 0

    second = await upsert_item_relations(
        db, [_edge(3, 4, RELATION_ADAPTATION, SOURCE_WIKIDATA, score=0.5)]
    )
    assert second.created == 0 and second.updated == 1

    row = (
        await db.execute(
            select(ItemRelation).where(
                ItemRelation.from_id == 3, ItemRelation.relation == RELATION_ADAPTATION
            )
        )
    ).scalar_one()
    assert row.score == pytest.approx(0.5)
    assert row.updated_at >= row.created_at


async def test_duplicates_inside_one_batch_are_collapsed(db):
    """``ON CONFLICT`` cannot affect one row twice in a single command."""
    result = await upsert_item_relations(
        db,
        [
            _edge(5, 6, RELATION_ADAPTATION, SOURCE_WIKIDATA, score=1.0),
            _edge(5, 6, RELATION_ADAPTATION, SOURCE_WIKIDATA, score=0.2),
        ],
    )
    assert result.created == 1
    row = (await db.execute(select(ItemRelation).where(ItemRelation.from_id == 5))).scalar_one()
    # Last one offered wins; the point is that neither raises.
    assert row.score == pytest.approx(0.2)


async def test_a_self_edge_is_dropped_by_the_writer_and_refused_by_the_database(db):
    result = await upsert_item_relations(
        db,
        [
            RelationWrite(
                from_type="MOVIE",
                from_id=7,
                to_type="MOVIE",
                to_id=7,
                relation=RELATION_ADAPTATION,
                source=SOURCE_WIKIDATA,
            )
        ],
    )
    assert result.written == 0
    assert await count_item_relations(db) == 0

    with pytest.raises(IntegrityError):
        await db.execute(
            text(
                "INSERT INTO item_relations (from_type, from_id, to_type, to_id, relation, source)"
                " VALUES ('MOVIE', 8, 'MOVIE', 8, 'ADAPTATION', 'WIKIDATA')"
            )
        )
    await db.rollback()


async def test_relations_are_read_from_both_sides_of_the_item(db):
    """Only one row per statement exists, so the reverse read is not optional."""
    await upsert_item_relations(
        db,
        [
            _edge(9, 10, RELATION_ADAPTATION, SOURCE_WIKIDATA),
            RelationWrite(
                from_type="BOOK",
                from_id=11,
                to_type="MOVIE",
                to_id=9,
                relation=RELATION_DERIVATIVE,
                source=SOURCE_WIKIDATA,
            ),
        ],
    )

    from_movie = await get_relations_for_item(db, "MOVIE", 9)
    assert len(from_movie) == 2

    from_book = await get_relations_for_item(db, "BOOK", 10)
    assert len(from_book) == 1
    assert from_book[0].from_type == "MOVIE"

    filtered = await get_relations_for_item(db, "MOVIE", 9, relation=RELATION_DERIVATIVE)
    assert [row.from_id for row in filtered] == [11]
    assert await get_relations_for_item(db, "MOVIE", 9, source=SOURCE_INTERNAL) == []


async def test_deletion_is_scoped_to_one_source(db):
    """The only deletion there is — feature 83's rows must survive a Wikidata purge."""
    await upsert_item_relations(
        db,
        [
            _edge(12, 13, RELATION_ADAPTATION, SOURCE_WIKIDATA),
            _edge(12, 13, RELATION_COOCCURRENCE, SOURCE_INTERNAL, score=0.9),
        ],
    )

    removed = await delete_relations_by_source(db, SOURCE_WIKIDATA)
    assert removed == 1
    assert await count_item_relations(db, source=SOURCE_WIKIDATA) == 0
    assert await count_item_relations(db, source=SOURCE_INTERNAL) == 1


async def test_the_edge_survives_independently_of_the_items_it_points_at(db):
    """Polymorphic reference, no FK — same contract as ``external_ids``/``credits``."""
    movie = Movie(title="Orphan Edge", slug="wd-orphan-edge", last_synced_at=datetime.now(UTC))
    db.add(movie)
    await db.flush()

    await upsert_item_relations(
        db, [_edge(movie.id, 999_999_999, RELATION_ADAPTATION, SOURCE_WIKIDATA)]
    )
    assert await count_item_relations(db) == 1


async def test_an_unknown_relation_is_refused_before_it_reaches_the_column(db):
    """``relation`` is a bare VARCHAR(20): a typo would insert perfectly happily.

    And then nothing would ever find those rows again — the ranker filters by
    the vocabulary. Silent loss is the failure mode this project keeps meeting
    (issues #7, #15, #20), so the single write path refuses instead, like
    ``backlogg/shared/codes.py`` does for an unknown role.
    """
    with pytest.raises(ValueError, match="COOCURRENCE"):
        await upsert_item_relations(db, [_edge(14, 15, "COOCURRENCE", SOURCE_INTERNAL)])
    assert await count_item_relations(db) == 0

    # The whole batch is refused, not just the bad row: a partial write would
    # leave the caller's cursor claiming work it did not do.
    with pytest.raises(ValueError):
        await upsert_item_relations(
            db,
            [
                _edge(14, 15, RELATION_ADAPTATION, SOURCE_WIKIDATA),
                _edge(14, 16, "ADAPTION", SOURCE_WIKIDATA),
            ],
        )
    assert await count_item_relations(db) == 0

    # Every member of the vocabulary passes, including the one feature 83 owns.
    for relation in sorted(RELATIONS):
        await upsert_item_relations(db, [_edge(17, 18, relation, SOURCE_WIKIDATA)])
    assert await count_item_relations(db) == len(RELATIONS)
