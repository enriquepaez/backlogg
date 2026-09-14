"""Feature 79 — the two Wikidata passes, against the real test database.

Every SPARQL answer is mocked (a fake ``WikidataClient``); nothing here
touches the network.  What *is* real is the database: the anchor lands in
``external_ids``, the edges land in ``item_relations`` and the cursors land in
``sync_watermarks``, so the acceptance criteria are checked against rows and
not against return values.

The acceptance list, mapped to the tests below:

1. *QID persisted in ``external_ids`` with ``source='WIKIDATA'``* —
   ``test_anchor_pass_persists_the_qid_in_external_ids``.
2. *Coverage report per item type* —
   ``test_anchor_pass_reports_coverage_per_item_type`` and
   ``test_coverage_denominator_is_the_linked_items_not_the_catalog``.
3. *``item_relations`` with ADAPTATION/DERIVATIVE and ``source='WIKIDATA'``* —
   ``test_relations_pass_writes_both_relations_with_the_wikidata_source``.
4. *Mapped by external identifier, never by title* —
   ``test_anchor_pass_asks_by_external_id_and_never_by_title`` and
   ``test_a_relation_end_outside_the_catalog_is_dropped_and_counted``.
5. *Idempotent and resumable, and it never deletes another source's relations*
   — ``test_running_both_passes_twice_creates_nothing_new``,
   ``test_a_pass_resumes_from_its_cursor_after_a_failure``,
   ``test_a_finished_walk_clears_its_cursor_so_next_month_starts_over`` and
   ``test_the_passes_never_touch_relations_of_another_source``.
6. *Scheduled GitHub Actions workflow* — ``test_the_workflow_is_scheduled``.
7. *Mocked SPARQL responses including an item absent from the catalog* — the
   whole module, and specifically criterion 4's second test.

The CLI's exit codes live in ``tests/test_wikidata_sync_cli.py``: the workflow
branches on them, and they are the one part of this feature that cannot be
tested from inside a running event loop.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from sqlalchemy import select

from backlogg.books.models import Book
from backlogg.movies.models import Movie
from backlogg.recommendations.adapters.wikidata import RelationStatement
from backlogg.recommendations.wikidata_sync import (
    ANCHOR_KIND,
    RELATIONS_ITEM_TYPE,
    RELATIONS_KIND,
    run_anchor_pass,
    run_relations_pass,
)
from backlogg.scheduler.repository import get_sync_watermark
from backlogg.shared.external_ids import ExternalId, upsert_external_id
from backlogg.shared.item_relations import (
    SOURCE_INTERNAL,
    SOURCE_WIKIDATA,
    ItemRelation,
    RelationWrite,
    count_item_relations,
    upsert_item_relations,
)

pytestmark = pytest.mark.asyncio

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "wikidata-sync.yml"


# ── Fixtures and stand-ins ───────────────────────────────────────────────────


def _session_factory(session):
    """Session factory whose context manager always yields the test session."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


class FakeWikidata:
    """Canned SPARQL answers, plus a record of everything it was asked.

    ``anchors`` is ``{property: {external_id: [qid, ...]}}`` and ``relations``
    is ``{subject_qid: [(property, object_qid), ...]}`` — the two shapes the
    real client returns.
    """

    def __init__(self, anchors: dict | None = None, relations: dict | None = None) -> None:
        self.anchors = anchors or {}
        self.relations = relations or {}
        self.anchor_calls: list[tuple[str, list[str]]] = []
        self.relation_calls: list[list[str]] = []

    async def resolve_qids(self, property_id, external_ids):
        self.anchor_calls.append((property_id, list(external_ids)))
        table = self.anchors.get(property_id, {})
        return {
            external_id: list(table[external_id])
            for external_id in external_ids
            if external_id in table
        }

    async def fetch_relations(self, qids):
        self.relation_calls.append(list(qids))
        statements = []
        for qid in qids:
            for property_id, to_qid in self.relations.get(qid, []):
                statements.append(
                    RelationStatement(from_qid=qid, property_id=property_id, to_qid=to_qid)
                )
        return statements


async def _make_movie(db, title: str, tmdb_id: str) -> Movie:
    movie = Movie(
        title=title,
        slug=f"wd-{title.lower().replace(' ', '-')}-{tmdb_id}",
        last_synced_at=datetime.now(UTC),
    )
    db.add(movie)
    await db.flush()
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", tmdb_id)
    return movie


async def _make_book(db, title: str, work_id: str) -> Book:
    book = Book(
        title=title,
        slug=f"wd-{title.lower().replace(' ', '-')}-{work_id}",
        last_synced_at=datetime.now(UTC),
    )
    db.add(book)
    await db.flush()
    await upsert_external_id(db, "BOOK", book.id, "OPEN_LIBRARY", work_id)
    return book


async def _anchor_of(db, item_type: str, item_id: int) -> str | None:
    row = (
        await db.execute(
            select(ExternalId.external_id).where(
                ExternalId.item_type == item_type,
                ExternalId.item_id == item_id,
                ExternalId.source == SOURCE_WIKIDATA,
            )
        )
    ).scalar_one_or_none()
    return row


# ── 1. The anchor lands in external_ids ──────────────────────────────────────


async def test_anchor_pass_persists_the_qid_in_external_ids(db):
    """The migration policy: every item that has a QID keeps it as an external id."""
    shining = await _make_movie(db, "The Shining", "694")
    unknown = await _make_movie(db, "Nothing In Wikidata", "42424242")
    await db.flush()

    client = FakeWikidata(anchors={"P4947": {"694": ["Q186341"]}})
    result = await run_anchor_pass(
        _session_factory(db), client=client, item_types=["MOVIE"], batch_size=50
    )

    assert await _anchor_of(db, "MOVIE", shining.id) == "Q186341"
    assert await _anchor_of(db, "MOVIE", unknown.id) is None
    assert result.resolved == 1
    # "Not in Wikidata" is a counted outcome, not an error and not a guess.
    assert result.missing == 1
    assert result.per_type["MOVIE"]["considered"] == 2


async def test_anchor_pass_asks_by_external_id_and_never_by_title(db):
    """Criterion 4: the join key is the id, and the title never leaves the DB."""
    await _make_movie(db, "Unique Title Never Sent", "777001")
    await db.flush()

    client = FakeWikidata(anchors={"P4947": {"777001": ["Q1"]}})
    await run_anchor_pass(_session_factory(db), client=client, item_types=["MOVIE"], batch_size=50)

    (property_id, asked) = client.anchor_calls[-1]
    assert property_id == "P4947"
    assert "777001" in asked
    assert all("Unique Title" not in value for value in asked)


async def test_an_id_claimed_by_two_entities_is_left_unanchored(db):
    """A wrong anchor is worse than none: a future migration would trust it."""
    ambiguous = await _make_movie(db, "Two Entities", "777002")
    await db.flush()

    client = FakeWikidata(anchors={"P4947": {"777002": ["Q1", "Q2"]}})
    result = await run_anchor_pass(
        _session_factory(db), client=client, item_types=["MOVIE"], batch_size=50
    )

    assert await _anchor_of(db, "MOVIE", ambiguous.id) is None
    assert result.ambiguous == 1
    assert result.resolved == 0


# ── 2. The coverage report ───────────────────────────────────────────────────


async def test_anchor_pass_reports_coverage_per_item_type(db):
    """Criterion 2: one line per content type, with its own numerator."""
    await _make_movie(db, "Anchored Movie", "778001")
    await _make_movie(db, "Unanchored Movie", "778002")
    await _make_book(db, "Anchored Book", "OL778001W")
    await db.flush()

    client = FakeWikidata(
        anchors={"P4947": {"778001": ["Q778001"]}, "P648": {"OL778001W": ["Q778002"]}}
    )
    result = await run_anchor_pass(
        _session_factory(db), client=client, item_types=["MOVIE", "BOOK"], batch_size=50
    )

    by_type = {row.item_type: row for row in result.coverage}
    assert set(by_type) == {"MOVIE", "BOOK"}
    assert by_type["MOVIE"].anchored == 1
    assert by_type["MOVIE"].linked == 2
    assert by_type["MOVIE"].coverage == pytest.approx(0.5)
    assert by_type["BOOK"].anchored == 1
    assert by_type["BOOK"].linked == 1
    assert by_type["BOOK"].coverage == pytest.approx(1.0)
    assert by_type["MOVIE"].source == "TMDB"
    assert by_type["BOOK"].source == "OPEN_LIBRARY"


async def test_coverage_denominator_is_the_linked_items_not_the_catalog(db):
    """An item with no id of its own could never be resolved by id anyway.

    Dividing by the whole catalog would blame this pass for a gap that belongs
    to the ingestion, so both numbers are reported and the ratio uses
    ``linked``.
    """
    await _make_movie(db, "Linked Movie", "779001")
    orphan = Movie(title="No External Id", slug="wd-orphan-779", last_synced_at=datetime.now(UTC))
    db.add(orphan)
    await db.flush()

    client = FakeWikidata(anchors={"P4947": {"779001": ["Q779001"]}})
    result = await run_anchor_pass(
        _session_factory(db), client=client, item_types=["MOVIE"], batch_size=50
    )

    coverage = result.coverage[0]
    assert coverage.linked == 1
    assert coverage.catalog_items == 2
    assert coverage.coverage == pytest.approx(1.0)


# ── 3. The relations land in item_relations ──────────────────────────────────


async def test_relations_pass_writes_both_relations_with_the_wikidata_source(db):
    """P144 -> ADAPTATION (film -> novel), P4969 -> DERIVATIVE (novel -> game)."""
    film = await _make_movie(db, "The Shining Film", "694")
    novel = await _make_book(db, "The Shining Novel", "OL470937W")
    await db.flush()
    await upsert_external_id(db, "MOVIE", film.id, SOURCE_WIKIDATA, "Q186341")
    await upsert_external_id(db, "BOOK", novel.id, SOURCE_WIKIDATA, "Q470937")
    await db.flush()

    client = FakeWikidata(
        relations={
            "Q186341": [("P144", "Q470937")],
            "Q470937": [("P4969", "Q186341")],
        }
    )
    result = await run_relations_pass(_session_factory(db), client=client, batch_size=50)

    rows = (await db.execute(select(ItemRelation))).scalars().all()
    edges = {
        (row.from_type, row.from_id, row.to_type, row.to_id, row.relation, row.source)
        for row in rows
    }
    assert edges == {
        ("MOVIE", film.id, "BOOK", novel.id, "ADAPTATION", "WIKIDATA"),
        ("BOOK", novel.id, "MOVIE", film.id, "DERIVATIVE", "WIKIDATA"),
    }
    assert all(row.score == pytest.approx(1.0) for row in rows)
    assert result.created == 2
    assert result.per_relation == {"ADAPTATION": 1, "DERIVATIVE": 1}


# ── 4. An end outside the catalog is dropped and counted ─────────────────────


async def test_a_relation_end_outside_the_catalog_is_dropped_and_counted(db):
    """The acceptance case: Wikidata knows a work this catalog does not have.

    It is dropped, never rescued by matching titles — there is no title path in
    this code at all — and it shows up in ``unmatched_ends`` so the operator can
    see how much of the graph falls outside the catalog.
    """
    film = await _make_movie(db, "Adapted Film", "780001")
    await db.flush()
    await upsert_external_id(db, "MOVIE", film.id, SOURCE_WIKIDATA, "Q780001")
    await db.flush()

    client = FakeWikidata(relations={"Q780001": [("P144", "Q999999999")]})
    result = await run_relations_pass(_session_factory(db), client=client, batch_size=50)

    assert result.statements == 1
    assert result.unmatched_ends == 1
    assert result.written == 0
    assert await count_item_relations(db, source=SOURCE_WIKIDATA) == 0


async def test_a_statement_pointing_at_the_item_itself_is_dropped(db):
    """The CHECK constraint would abort the whole batch; the pass drops it first."""
    film = await _make_movie(db, "Self Referential", "780002")
    await db.flush()
    await upsert_external_id(db, "MOVIE", film.id, SOURCE_WIKIDATA, "Q780002")
    await db.flush()

    client = FakeWikidata(relations={"Q780002": [("P144", "Q780002")]})
    result = await run_relations_pass(_session_factory(db), client=client, batch_size=50)

    assert result.self_edges == 1
    assert await count_item_relations(db) == 0


# ── 5. Idempotency, resumability and the shared table ────────────────────────


async def test_running_both_passes_twice_creates_nothing_new(db):
    film = await _make_movie(db, "Idempotent Film", "781001")
    novel = await _make_book(db, "Idempotent Novel", "OL781001W")
    await db.flush()

    anchors = {"P4947": {"781001": ["Q781001"]}, "P648": {"OL781001W": ["Q781002"]}}
    relations = {"Q781001": [("P144", "Q781002")]}

    for _ in range(2):
        await run_anchor_pass(
            _session_factory(db),
            client=FakeWikidata(anchors=anchors),
            item_types=["MOVIE", "BOOK"],
            batch_size=50,
        )
    second = await run_relations_pass(
        _session_factory(db), client=FakeWikidata(relations=relations), batch_size=50
    )
    assert second.created == 1

    third = await run_relations_pass(
        _session_factory(db), client=FakeWikidata(relations=relations), batch_size=50
    )
    assert third.created == 0
    assert third.updated == 1

    assert await _anchor_of(db, "MOVIE", film.id) == "Q781001"
    assert await _anchor_of(db, "BOOK", novel.id) == "Q781002"
    assert await count_item_relations(db, source=SOURCE_WIKIDATA) == 1


async def test_a_pass_resumes_from_its_cursor_after_a_failure(db):
    """A run killed mid-walk redoes one batch and nothing else."""
    first = await _make_movie(db, "Batch One", "782001")
    second = await _make_movie(db, "Batch Two", "782002")
    await db.flush()

    anchors = {"P4947": {"782001": ["Q782001"], "782002": ["Q782002"]}}

    class DyingClient(FakeWikidata):
        async def resolve_qids(self, property_id, external_ids):
            if len(self.anchor_calls) == 1:
                raise RuntimeError("the runner went away")
            return await super().resolve_qids(property_id, external_ids)

    with pytest.raises(RuntimeError):
        await run_anchor_pass(
            _session_factory(db),
            client=DyingClient(anchors=anchors),
            item_types=["MOVIE"],
            batch_size=1,
        )

    assert await _anchor_of(db, "MOVIE", first.id) == "Q782001"
    assert await _anchor_of(db, "MOVIE", second.id) is None
    watermark = await get_sync_watermark(db, SOURCE_WIKIDATA, ANCHOR_KIND, "MOVIE")
    assert watermark is not None and watermark.cursor_value is not None
    cursor_after_death = int(watermark.cursor_value)

    resumed = FakeWikidata(anchors=anchors)
    await run_anchor_pass(_session_factory(db), client=resumed, item_types=["MOVIE"], batch_size=1)

    # The resumed run never re-asks for the id the dead one had already written.
    assert all("782001" not in asked for _, asked in resumed.anchor_calls)
    assert await _anchor_of(db, "MOVIE", second.id) == "Q782002"
    assert cursor_after_death > 0


async def test_a_finished_walk_clears_its_cursor_so_next_month_starts_over(db):
    """A monthly job that only looked at new rows would never pick up an edit."""
    await _make_movie(db, "Finished Walk", "783001")
    await db.flush()

    await run_anchor_pass(
        _session_factory(db),
        client=FakeWikidata(anchors={"P4947": {"783001": ["Q783001"]}}),
        item_types=["MOVIE"],
        batch_size=50,
    )
    watermark = await get_sync_watermark(db, SOURCE_WIKIDATA, ANCHOR_KIND, "MOVIE")
    assert watermark is not None
    assert watermark.cursor_value is None

    await run_relations_pass(_session_factory(db), client=FakeWikidata(), batch_size=50)
    relations_watermark = await get_sync_watermark(
        db, SOURCE_WIKIDATA, RELATIONS_KIND, RELATIONS_ITEM_TYPE
    )
    assert relations_watermark is not None
    assert relations_watermark.cursor_value is None


async def test_the_passes_never_touch_relations_of_another_source(db):
    """``item_relations`` is shared with feature 83 — no wide DELETE, ever."""
    film = await _make_movie(db, "Shared Table Film", "784001")
    novel = await _make_book(db, "Shared Table Novel", "OL784001W")
    await db.flush()
    await upsert_external_id(db, "MOVIE", film.id, SOURCE_WIKIDATA, "Q784001")
    await upsert_external_id(db, "BOOK", novel.id, SOURCE_WIKIDATA, "Q784002")
    await db.flush()

    # What feature 83 will write: the same pair, a different layer.
    await upsert_item_relations(
        db,
        [
            RelationWrite(
                from_type="MOVIE",
                from_id=film.id,
                to_type="BOOK",
                to_id=novel.id,
                relation="COOCCURRENCE",
                source=SOURCE_INTERNAL,
                score=0.42,
            )
        ],
    )
    await db.flush()

    await run_relations_pass(
        _session_factory(db),
        client=FakeWikidata(relations={"Q784001": [("P144", "Q784002")]}),
        batch_size=50,
    )

    assert await count_item_relations(db, source=SOURCE_INTERNAL) == 1
    assert await count_item_relations(db, source=SOURCE_WIKIDATA) == 1
    internal = (
        await db.execute(select(ItemRelation).where(ItemRelation.source == SOURCE_INTERNAL))
    ).scalar_one()
    assert internal.score == pytest.approx(0.42)


# ── 6. The workflow is scheduled ─────────────────────────────────────────────


async def test_the_workflow_is_scheduled():
    """Criterion 6: cron + workflow_dispatch, the nightly-sync.yml scheduling shape."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    # PyYAML parses the bare ``on:`` key as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert "schedule" in triggers
    assert triggers["schedule"][0]["cron"].split()[2] == "3"  # monthly, day 3
    assert "workflow_dispatch" in triggers

    job = workflow["jobs"]["wikidata"]
    # It runs the script against Neon on the runner, like backfill-sync.yml —
    # not a curl to a Render admin endpoint, which could not hold the pass.
    assert job["env"]["DATABASE_URL"].strip() == "${{ secrets.DATABASE_URL }}"
    steps = " ".join(step.get("run", "") for step in job["steps"])
    assert "scripts/sync_wikidata.py" in steps


async def test_one_qid_anchoring_two_item_types_gets_edges_for_both(db):
    """Wikidata sometimes keeps a novel and its film on a single entity.

    ``uq_external_id`` is scoped per ``item_type``, so both catalog rows can
    legitimately hold the same QID. Attributing the statements to only one of
    them would be a silent loss.
    """
    film = await _make_movie(db, "Conflated Film", "785001")
    novel = await _make_book(db, "Conflated Novel", "OL785001W")
    target = await _make_book(db, "Source Novel", "OL785002W")
    await db.flush()
    await upsert_external_id(db, "MOVIE", film.id, SOURCE_WIKIDATA, "Q785001")
    await upsert_external_id(db, "BOOK", novel.id, SOURCE_WIKIDATA, "Q785001")
    await upsert_external_id(db, "BOOK", target.id, SOURCE_WIKIDATA, "Q785002")
    await db.flush()

    client = FakeWikidata(relations={"Q785001": [("P144", "Q785002")]})
    result = await run_relations_pass(_session_factory(db), client=client, batch_size=50)

    edges = {
        (row.from_type, row.from_id)
        for row in (await db.execute(select(ItemRelation))).scalars().all()
    }
    assert edges == {("MOVIE", film.id), ("BOOK", novel.id)}
    assert result.created == 2


# ── The wall-clock budget: the seam that produces exit 2 ─────────────────────


class _ProgressClock:
    """Monotonic clock that jumps past the deadline once a batch has been done.

    Driven by **observed progress** (how many SPARQL calls the fake client has
    served) rather than by how many times ``expired()`` happens to poll it, so
    the test pins the behaviour — "the budget expires after the first batch" —
    and not the polling pattern of the implementation.
    """

    def __init__(self, calls: list, jump: float = 61.0) -> None:
        self._calls = calls
        self._jump = jump
        self.t0 = 1000.0

    def __call__(self) -> float:
        return self.t0 + (self._jump if self._calls else 0.0)


async def _wikidata_row_id(db, item_type: str, item_id: int) -> int:
    return (
        await db.execute(
            select(ExternalId.id).where(
                ExternalId.item_type == item_type,
                ExternalId.item_id == item_id,
                ExternalId.source == SOURCE_WIKIDATA,
            )
        )
    ).scalar_one()


async def test_the_anchor_pass_stops_on_its_time_budget_and_keeps_its_cursor(db):
    """The budget is what turns "Actions killed us" into a resumable exit 2.

    Without this the job runs until GitHub kills it at 350 min: the step summary
    is lost, the ``::warning::`` never fires and ``docs/operations.md``'s
    "re-dispatch to continue" has nothing to continue from.
    """
    first = await _make_movie(db, "Budget One", "786001")
    second = await _make_movie(db, "Budget Two", "786002")
    third = await _make_movie(db, "Budget Three", "786003")
    await db.flush()

    anchors = {"P4947": {"786001": ["Q786001"], "786002": ["Q786002"], "786003": ["Q786003"]}}
    client = FakeWikidata(anchors=anchors)
    result = await run_anchor_pass(
        _session_factory(db),
        client=client,
        item_types=["MOVIE"],
        batch_size=1,
        budget_minutes=1,
        clock=_ProgressClock(client.anchor_calls),
    )

    assert result.completed is False
    assert result.batches == 1
    assert await _anchor_of(db, "MOVIE", first.id) == "Q786001"
    assert await _anchor_of(db, "MOVIE", second.id) is None
    assert await _anchor_of(db, "MOVIE", third.id) is None

    # The cursor is the committed batch's row id — not None ("walk finished")
    # and not 0 ("never ran").
    watermark = await get_sync_watermark(db, SOURCE_WIKIDATA, ANCHOR_KIND, "MOVIE")
    assert watermark is not None
    assert watermark.cursor_value is not None
    expected = (
        await db.execute(
            select(ExternalId.id).where(
                ExternalId.item_type == "MOVIE",
                ExternalId.item_id == first.id,
                ExternalId.source == "TMDB",
            )
        )
    ).scalar_one()
    assert int(watermark.cursor_value) == expected

    # Re-dispatch: continues, never re-asks for what the killed run already did.
    resumed = FakeWikidata(anchors=anchors)
    again = await run_anchor_pass(
        _session_factory(db), client=resumed, item_types=["MOVIE"], batch_size=1
    )
    asked = [value for _, ids in resumed.anchor_calls for value in ids]
    assert "786001" not in asked
    assert sorted(asked) == ["786002", "786003"]
    assert again.completed is True
    assert await _anchor_of(db, "MOVIE", second.id) == "Q786002"
    assert await _anchor_of(db, "MOVIE", third.id) == "Q786003"


async def test_the_relations_pass_stops_on_its_time_budget_and_keeps_its_cursor(db):
    """Same seam on the second pass, whose cursor is (WIKIDATA, …, ALL)."""
    first = await _make_movie(db, "Rel Budget One", "787001")
    second = await _make_movie(db, "Rel Budget Two", "787002")
    third = await _make_movie(db, "Rel Budget Three", "787003")
    target = await _make_book(db, "Rel Budget Target", "OL787001W")
    await db.flush()
    # Anchored in this order, so the walk over external_ids.id visits the three
    # movies first and the shared target last.
    await upsert_external_id(db, "MOVIE", first.id, SOURCE_WIKIDATA, "Q787001")
    await upsert_external_id(db, "MOVIE", second.id, SOURCE_WIKIDATA, "Q787002")
    await upsert_external_id(db, "MOVIE", third.id, SOURCE_WIKIDATA, "Q787003")
    await upsert_external_id(db, "BOOK", target.id, SOURCE_WIKIDATA, "Q787009")
    await db.flush()

    relations = {
        "Q787001": [("P144", "Q787009")],
        "Q787002": [("P144", "Q787009")],
        "Q787003": [("P144", "Q787009")],
    }
    client = FakeWikidata(relations=relations)
    result = await run_relations_pass(
        _session_factory(db),
        client=client,
        batch_size=1,
        budget_minutes=1,
        clock=_ProgressClock(client.relation_calls),
    )

    assert result.completed is False
    assert result.batches == 1
    assert result.created == 1
    edges = {
        (row.from_type, row.from_id)
        for row in (await db.execute(select(ItemRelation))).scalars().all()
    }
    assert edges == {("MOVIE", first.id)}

    watermark = await get_sync_watermark(db, SOURCE_WIKIDATA, RELATIONS_KIND, RELATIONS_ITEM_TYPE)
    assert watermark is not None
    assert watermark.cursor_value is not None
    assert int(watermark.cursor_value) == await _wikidata_row_id(db, "MOVIE", first.id)

    resumed = FakeWikidata(relations=relations)
    again = await run_relations_pass(_session_factory(db), client=resumed, batch_size=1)
    asked = [qid for call in resumed.relation_calls for qid in call]
    assert "Q787001" not in asked
    assert again.completed is True
    assert await count_item_relations(db, source=SOURCE_WIKIDATA) == 3


# ── The anchor counter reports links, not attempts ───────────────────────────


async def test_a_qid_already_claimed_by_another_item_is_not_counted_as_anchored(db):
    """Issue #22 reaches this pass too: the incumbent keeps the QID.

    Reporting the loser as ``anchored`` would print a number ``external_ids``
    cannot back — the silent discrepancy that chained issues #7, #15 and #20.
    """
    winner = await _make_movie(db, "Claim Winner", "788001")
    loser = await _make_movie(db, "Claim Loser", "788002")
    await db.flush()

    client = FakeWikidata(anchors={"P4947": {"788001": ["Q788001"], "788002": ["Q788001"]}})
    result = await run_anchor_pass(
        _session_factory(db), client=client, item_types=["MOVIE"], batch_size=50
    )

    assert await _anchor_of(db, "MOVIE", winner.id) == "Q788001"
    assert await _anchor_of(db, "MOVIE", loser.id) is None
    assert result.resolved == 1
    assert result.unlinked == 1
    assert result.skipped_links == 1
    # The four buckets partition ``considered`` exactly.
    assert (
        result.resolved + result.missing + result.ambiguous + result.unlinked == result.considered
    )
    # And the reported count matches what the table actually holds.
    assert result.coverage[0].anchored == 1
