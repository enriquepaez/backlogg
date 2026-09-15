"""Feature 75 — the storage half: persistence and cosine search over ``halfvec``.

What is under test, and why each of these earns a test:

- a vector **survives the round trip through ``halfvec``**. This is the one
  thing the whole feature rests on and it goes through three conversions
  nobody would notice breaking: Python list -> ``float8[]`` -> ``halfvec`` on
  the way in, ``halfvec`` -> ``real[]`` -> Python list on the way out. There is
  no pgvector Python package in this project (deliberately — it would put numpy
  in the image Render deploys), so those casts are ours to get right;
- **cosine ranks across types**, which is the entire point of the layer: the
  nearest neighbour of a book has to be able to be a film. A test that only
  ever compared two movies would pass with a design that cannot do the one job
  this table exists for;
- **the upsert is idempotent**, reported as created/updated rather than
  silently — the monthly job is re-dispatched on purpose and a second pass that
  inserted duplicates would break ``uq_item_embedding`` or, worse, not break it;
- an item **outside the subset** answers "nothing", not an error. The subset is
  bounded by design (Neon free headroom), so "this item has no vector" is an
  ordinary state that feature 80 must be able to fall back from;
- the write frontier **refuses** an unknown ``item_type`` and a wrong-width
  vector. Both would otherwise be found much later: the first as rows no reader
  ever finds again, the second as a Postgres error that kills a whole batch
  because one row in it was malformed;
- ``storage_report`` measures table and index **apart**. The acceptance list
  asks for that number, and it is the number that says whether this layer still
  fits in what is left of a 512 MB Neon project.
"""

import pytest

from backlogg.core.config import settings
from backlogg.recommendations.embeddings import format_storage_report
from backlogg.shared.item_embeddings import (
    EmbeddingWrite,
    StorageReport,
    count_by_item_type,
    count_item_embeddings,
    get_embedding_column_dim,
    get_item_embedding,
    get_similar_by_item,
    get_similar_by_vector,
    storage_report,
    upsert_item_embeddings,
)

# No module-level ``pytest.mark.asyncio``: since the formatter test below is a
# pure function, the file mixes sync and async tests, and the marker would
# warn on every sync one. ``asyncio_mode = "auto"`` already marks the
# coroutines — same arrangement as tests/recommendations/test_embedding_pass.py.

DIM = settings.EMBEDDING_DIM
MODEL = "test-model-v1"


def _axis(index: int, sign: float = 1.0) -> list[float]:
    """A unit vector along one axis — cosine against it is exactly predictable."""
    vector = [0.0] * DIM
    vector[index] = sign
    return vector


def _blend(near: int, far: int, weight: float) -> list[float]:
    """Unit vector leaning ``weight`` towards ``near`` and the rest towards ``far``."""
    import math

    vector = [0.0] * DIM
    vector[near] = weight
    vector[far] = math.sqrt(max(0.0, 1.0 - weight * weight))
    return vector


async def _write(db, item_type: str, item_id: int, vector: list[float], *, digest: str = "h"):
    return await upsert_item_embeddings(
        db,
        [
            EmbeddingWrite(
                item_type=item_type,
                item_id=item_id,
                embedding=vector,
                model=MODEL,
                source_hash=digest,
            )
        ],
    )


# ── Round trip ────────────────────────────────────────────────────────────────


async def test_vector_survives_the_round_trip_through_halfvec(db):
    """Stored and read back component by component, within half precision.

    ``halfvec`` is a lossy format on purpose — it is what makes the layer fit on
    disk — so the assertion is a tolerance, not equality. 1e-3 is two orders of
    magnitude tighter than the ~1e-2 relative error of IEEE half at these
    magnitudes would allow for a wrong *conversion*, and loose enough never to
    flake on the rounding that is expected.
    """
    original = _blend(0, 7, 0.6)
    await _write(db, "MOVIE", 101, original)

    stored = await get_item_embedding(db, "MOVIE", 101)
    assert stored is not None
    assert len(stored.embedding) == DIM
    for expected, actual in zip(original, stored.embedding, strict=True):
        assert abs(expected - actual) < 1e-3
    assert stored.model == MODEL


async def test_an_item_with_no_vector_reads_as_absent_not_as_an_error(db):
    """The bounded subset means "not embedded" is normal, not exceptional."""
    assert await get_item_embedding(db, "GAME", 999_001) is None
    assert await get_similar_by_item(db, "GAME", 999_001) == []


# ── Cosine, and the fact that it crosses types ────────────────────────────────


async def test_cosine_search_ranks_neighbours_across_content_types(db):
    """The nearest neighbour of a book is a film, and the ranking says so.

    The fixture is built so the correct order is *not* the insertion order and
    *not* grouped by type: from the book, the closest row is a MOVIE, then a
    SERIES at right angles, then a GAME pointing the opposite way. If anything
    ever filtered or biased by type, this ordering is the first thing to break.
    """
    await _write(db, "BOOK", 201, _axis(0))
    await _write(db, "MOVIE", 202, _blend(0, 5, 0.99))
    await _write(db, "SERIES", 203, _axis(5))
    await _write(db, "GAME", 204, _axis(0, -1.0))

    neighbours = await get_similar_by_item(db, "BOOK", 201, limit=10)

    assert [(n.item_type, n.item_id) for n in neighbours] == [
        ("MOVIE", 202),
        ("SERIES", 203),
        ("GAME", 204),
    ]
    assert neighbours[0].score == pytest.approx(0.99, abs=1e-2)
    assert neighbours[1].score == pytest.approx(0.0, abs=1e-2)
    assert neighbours[2].score == pytest.approx(-1.0, abs=1e-2)


async def test_similarity_can_be_narrowed_to_some_types_and_never_returns_the_anchor(db):
    """Feature 80 needs "more of another type"; the anchor is never a candidate."""
    await _write(db, "BOOK", 211, _axis(0))
    await _write(db, "BOOK", 212, _blend(0, 5, 0.95))
    await _write(db, "MOVIE", 213, _blend(0, 5, 0.90))

    same_type_excluded = await get_similar_by_item(db, "BOOK", 211, limit=10)
    assert ("BOOK", 211) not in [(n.item_type, n.item_id) for n in same_type_excluded]

    only_movies = await get_similar_by_item(db, "BOOK", 211, limit=10, item_types=["MOVIE"])
    assert [(n.item_type, n.item_id) for n in only_movies] == [("MOVIE", 213)]


async def test_search_by_an_arbitrary_vector_orders_by_cosine(db):
    """The by-vector read exists for callers that have a vector and no anchor row."""
    await _write(db, "MOVIE", 221, _axis(3))
    await _write(db, "GAME", 222, _axis(4))

    neighbours = await get_similar_by_vector(db, _axis(3), limit=5)
    assert [(n.item_type, n.item_id) for n in neighbours] == [("MOVIE", 221), ("GAME", 222)]
    assert neighbours[0].score == pytest.approx(1.0, abs=1e-3)

    excluded = await get_similar_by_vector(db, _axis(3), limit=5, exclude=("MOVIE", 221))
    assert [(n.item_type, n.item_id) for n in excluded] == [("GAME", 222)]


# ── Idempotency of the write ──────────────────────────────────────────────────


async def test_reoffering_the_same_item_updates_instead_of_duplicating(db):
    """Re-dispatching the monthly job must not grow the table."""
    first = await _write(db, "MOVIE", 231, _axis(1), digest="hash-1")
    assert (first.created, first.updated) == (1, 0)

    second = await _write(db, "MOVIE", 231, _axis(2), digest="hash-2")
    assert (second.created, second.updated) == (0, 1)

    assert await count_item_embeddings(db, item_type="MOVIE") == 1
    stored = await get_item_embedding(db, "MOVIE", 231)
    assert stored is not None
    assert stored.source_hash == "hash-2"
    assert stored.embedding[2] == pytest.approx(1.0, abs=1e-3)


async def test_a_duplicate_inside_one_batch_is_collapsed(db):
    """Postgres refuses an ON CONFLICT that touches the same key twice.

    Left to Postgres this is not a partial failure, it is the loss of the whole
    batch — so the write path collapses duplicates itself, last one winning.
    """
    result = await upsert_item_embeddings(
        db,
        [
            EmbeddingWrite("BOOK", 241, _axis(1), MODEL, "a"),
            EmbeddingWrite("BOOK", 241, _axis(2), MODEL, "b"),
        ],
    )
    assert result.written == 1
    stored = await get_item_embedding(db, "BOOK", 241)
    assert stored is not None
    assert stored.source_hash == "b"


async def test_counts_are_reported_per_content_type(db):
    """The cross-type coverage check the job logs, and feature 80 depends on."""
    await _write(db, "MOVIE", 251, _axis(1))
    await _write(db, "MOVIE", 252, _axis(2))
    await _write(db, "BOOK", 253, _axis(3))

    assert await count_by_item_type(db) == {"MOVIE": 2, "BOOK": 1}
    assert await count_item_embeddings(db) == 3


# ── The write frontier refuses what would be lost silently ────────────────────


async def test_an_unknown_item_type_is_refused(db):
    with pytest.raises(ValueError, match="unknown item_type"):
        await upsert_item_embeddings(db, [EmbeddingWrite("FILM", 261, _axis(1), MODEL, "h")])


async def test_a_vector_of_the_wrong_width_is_refused_before_the_batch_is_sent(db):
    """One malformed row must not cost the other 255 in its batch."""
    with pytest.raises(ValueError, match="EMBEDDING_DIM"):
        await upsert_item_embeddings(
            db,
            [
                EmbeddingWrite("MOVIE", 271, _axis(1), MODEL, "h"),
                EmbeddingWrite("MOVIE", 272, [0.0] * (DIM - 1), MODEL, "h"),
            ],
        )
    assert await count_item_embeddings(db) == 0


# ── The disk measurement the acceptance list asks for ─────────────────────────


async def test_storage_report_measures_table_and_index_apart(db):
    """Not a size assertion — a shape assertion on the instrument itself.

    The real number is produced by the job against the real subset and lands in
    ``docs/operations.md``; what a test can pin is that the measurement counts
    the rows it should and reports the index separately from the table, because
    a report that folded them together would hide which half is the problem.
    """
    for offset in range(5):
        await _write(db, "MOVIE", 281 + offset, _axis(offset))
    await db.flush()

    report = await storage_report(db)

    assert report.rows == 5
    assert report.table_bytes > 0
    assert report.index_bytes > 0
    assert report.total_bytes == report.table_bytes + report.index_bytes + report.toast_bytes
    assert report.bytes_per_row > 0


async def test_the_ann_index_is_measured_apart_from_the_btrees(db):
    """``pg_indexes_size`` is HNSW **plus** ``uq_item_embedding`` plus the PK.

    This half is about the *measurement*: that both figures really come out of
    Postgres, that neither is empty and that they partition the index total.
    Whether the formatter then prints them under the right labels is pinned by
    ``test_the_report_prints_the_ann_figure_under_the_ann_label`` below — it
    cannot be asserted here, because five rows of fixture render every index as
    ``0.0 MB`` and any comparison between them is vacuous at that scale.
    """
    for offset in range(5):
        await _write(db, "GAME", 291 + offset, _axis(offset))
    await db.flush()

    report = await storage_report(db)

    assert report.ann_index_bytes > 0
    assert report.btree_index_bytes > 0
    assert report.ann_index_bytes + report.btree_index_bytes == report.index_bytes


#: The real measurement of 2026-09-15 over the 35.215-item development catalog,
#: in bytes, exactly as ``storage_report`` read it from Postgres. Used as a
#: fixture rather than invented numbers so the expected output below is
#: literally the table in ``docs/schema.md`` and ``docs/operations.md``: if the
#: formatter and the documentation ever disagree, this test says so.
_MEASURED = StorageReport(
    rows=35_215,
    table_bytes=36_102_144,
    index_bytes=43_532_288,
    ann_index_bytes=41_172_992,
    toast_bytes=8_192,
)


def test_the_report_prints_the_ann_figure_under_the_ann_label():
    """The labels are contract, asserted at a scale where the figures differ.

    ``format_storage_report`` is a pure function, so it is exercised with the
    measured report directly instead of through the database. That is the whole
    point: the DB-backed test above writes five rows, and at five rows the HNSW
    index and the index *total* both render as ``0.0 MB`` — so an assertion
    that the ANN line carries the ANN figure passes even when it carries the
    total. The regression this is here to stop (printing ``index_bytes`` under
    the ``hnsw (ann)`` label, which would credit the ANN index with ~2 MB of
    b-trees and make an operator believe there is more Neon headroom than there
    is) only becomes visible once the two numbers are far enough apart to
    render differently. Hence 39,3 vs 41,5 and not 0,0 vs 0,0.
    """
    lines = format_storage_report(_MEASURED)

    assert lines == [
        "rows                 35215",
        "heap (data)        34.4 MB",
        "toast               0.0 MB",
        "indexes            41.5 MB",
        "  hnsw (ann)       39.3 MB",
        "  b-trees           2.2 MB",
        "TOTAL              76.0 MB",
        "per item           2262 bytes",
    ]

    # Spelled out again, independently of the exact spacing above, so that a
    # cosmetic change to the format string cannot quietly take the substance
    # with it: the ANN line must carry the ANN figure and never the total.
    ann_line = next(line for line in lines if "hnsw" in line)
    assert "39.3 MB" in ann_line
    assert "41.5 MB" not in ann_line
    assert not any(line.startswith("hnsw index") for line in lines)


async def test_the_column_width_is_readable_and_matches_the_configured_dimension(db):
    """The guard that stops EMBEDDING_DIM drifting away from the migrated column."""
    assert await get_embedding_column_dim(db) == settings.EMBEDDING_DIM
