"""End-to-end tests for ``scripts/seed_openlibrary_books.py`` (feature 87).

The five phases are driven with the recorded dump fragment instead of the
network (``stream_dump_lines`` is patched), and the write phase runs against
the real test database — the same shape ``tests/test_sync_genre_slug_collision``
uses for the nightly job.

What is proved here and nowhere else: the phases chain into a catalog row with
its external id, its genres and its AUTHOR credits; seeding twice does not
duplicate or lose anything; and a phase whose artifact is already in the work
dir is skipped, which is what makes an interrupted run cheap to resume.
"""

import importlib.util
import logging
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select

from backlogg.books.adapters import openlibrary_dump as dump
from backlogg.books.models import Book, BookGenre, book_genres_join
from backlogg.shared.external_ids import ExternalId, upsert_external_id
from backlogg.shared.models import Credit, Person
from tests.books import dump_fixtures as fx

# ── Load the script as a module (scripts/ is not an installed package) ───────

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "seed_openlibrary_books.py"
_spec = importlib.util.spec_from_file_location("seed_openlibrary_books", _SCRIPT_PATH)
seed = importlib.util.module_from_spec(_spec)
sys.modules["seed_openlibrary_books"] = seed
_spec.loader.exec_module(seed)


_FIXTURE_STREAMS = {
    dump.DUMP_READING_LOG: fx.reading_log_lines,
    dump.DUMP_EDITIONS: fx.edition_lines,
    dump.DUMP_WORKS: fx.work_lines,
    dump.DUMP_AUTHORS: fx.author_lines,
}


def _fixture_stream(name: str):
    return iter(_FIXTURE_STREAMS[name]())


def _exploding_stream(name: str):
    raise AssertionError(f"phase for {name} should have been skipped, its artifact exists")


def _session_factory(db):
    """A factory whose context manager hands the test's session to the script."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _patched(db, monkeypatch, *, stream=_fixture_stream):
    monkeypatch.setattr(seed, "stream_dump_lines", stream)
    monkeypatch.setattr(seed, "async_session_factory", _session_factory(db))
    # REFRESH MATERIALIZED VIEW CONCURRENTLY cannot run inside the test's
    # transaction, and the view is not what these tests are about.
    monkeypatch.setattr(seed, "refresh_catalog_search", AsyncMock())
    # The script disposes the app engine when it finishes; the test session
    # comes from the suite's own engine, so leave the app one alone (the
    # attribute on AsyncEngine is read-only, hence patching the module name).
    monkeypatch.setattr(seed, "engine", MagicMock(dispose=AsyncMock()))


async def _run(db, monkeypatch, tmp_path, *, phase=None, force=False, stream=_fixture_stream):
    _patched(db, monkeypatch, stream=stream)
    return await seed.run(tmp_path, phase, force)


@pytest.fixture
def work_dir(tmp_path):
    return tmp_path / "openlibrary-seed"


# ── The whole pipeline ───────────────────────────────────────────────────────


async def test_run_seeds_the_selected_catalog(db, monkeypatch, work_dir):
    summary = await _run(db, monkeypatch, work_dir)

    # Phase 1: only works at or above the whitelist floor (5 shelvings).
    assert summary["reading-log"]["min_shelvings"] == 5
    assert summary["reading-log"]["whitelist"] == 8

    # Phase 2: of those, only the ones clearing the feature-73 filter, which
    # needs the editions the fragment carries.
    assert summary["editions"]["selected"] == 4
    assert summary["works"]["found"] == 4

    # Phase 5: one row per selected work, none rejected.
    assert summary["load"]["synced"] == 4
    assert summary["load"]["errors"] == 0
    assert summary["load"]["skipped_links"] == 0
    assert summary["load"]["untitled"] == 0

    docs = fx.search_docs()
    for work_id in (
        fx.WORK_LOVE_HYPOTHESIS,
        fx.WORK_CANT_HURT_ME,
        fx.WORK_SUMMER_TRILOGY,
        fx.WORK_PSICOLOGIA_OSCURA,
    ):
        link = (
            await db.execute(
                select(ExternalId).where(
                    ExternalId.item_type == "BOOK",
                    ExternalId.source == "OPEN_LIBRARY",
                    ExternalId.external_id == work_id,
                )
            )
        ).scalar_one()
        book = (await db.execute(select(Book).where(Book.id == link.item_id))).scalar_one()
        assert book.title == docs[work_id]["title"]
        assert book.first_publish_date.year == docs[work_id]["first_publish_year"]
        assert book.poster_url and str(docs[work_id]["cover_i"]) in book.poster_url

    # The work under the English shelving floor is not in the catalog.
    assert (
        await db.execute(
            select(func.count())
            .select_from(ExternalId)
            .where(ExternalId.external_id == fx.WORK_ULTRAMARATHON)
        )
    ).scalar_one() == 0


async def test_run_writes_genres_and_author_credits(db, monkeypatch, work_dir):
    await _run(db, monkeypatch, work_dir)

    link = (
        await db.execute(
            select(ExternalId).where(
                ExternalId.item_type == "BOOK",
                ExternalId.external_id == fx.WORK_LOVE_HYPOTHESIS,
            )
        )
    ).scalar_one()
    book = (await db.execute(select(Book).where(Book.id == link.item_id))).scalar_one()

    genre_slugs = set(
        (
            await db.execute(
                select(BookGenre.slug)
                .join(book_genres_join, BookGenre.id == book_genres_join.c.genre_id)
                .where(book_genres_join.c.book_id == book.id)
            )
        ).scalars()
    )
    # Derived from the *raw* ddc/lcc notation the editions carry, and equal to
    # what search.json yields for the same work (proved in
    # tests/books/test_openlibrary_dump_fixture.py).
    assert genre_slugs

    credits = (
        (
            await db.execute(
                select(Credit).where(Credit.item_type == "BOOK", Credit.item_id == book.id)
            )
        )
        .scalars()
        .all()
    )
    assert credits and {credit.role for credit in credits} == {"AUTHOR"}

    person = (
        await db.execute(select(Person).where(Person.id == credits[0].person_id))
    ).scalar_one()
    assert person.name
    author_link = (
        await db.execute(
            select(ExternalId).where(
                ExternalId.item_type == "PERSON",
                ExternalId.source == "OPEN_LIBRARY",
                ExternalId.item_id == person.id,
            )
        )
    ).scalar_one()
    assert author_link.external_id.endswith("A")


# ── Idempotence ──────────────────────────────────────────────────────────────


async def test_seeding_twice_neither_duplicates_nor_loses(db, monkeypatch, work_dir):
    """The write phase is an upsert, so re-running it is safe by construction."""
    await _run(db, monkeypatch, work_dir)

    books_before = (await db.execute(select(func.count()).select_from(Book))).scalar_one()
    people_before = (await db.execute(select(func.count()).select_from(Person))).scalar_one()
    credits_before = (await db.execute(select(func.count()).select_from(Credit))).scalar_one()
    links_before = (await db.execute(select(func.count()).select_from(ExternalId))).scalar_one()

    second = await _run(db, monkeypatch, work_dir, phase="load")

    assert second["load"]["synced"] == 4
    assert second["load"]["errors"] == 0
    assert (await db.execute(select(func.count()).select_from(Book))).scalar_one() == books_before
    assert (
        await db.execute(select(func.count()).select_from(Person))
    ).scalar_one() == people_before
    assert (
        await db.execute(select(func.count()).select_from(Credit))
    ).scalar_one() == credits_before
    assert (
        await db.execute(select(func.count()).select_from(ExternalId))
    ).scalar_one() == links_before


# ── Resumability ─────────────────────────────────────────────────────────────


async def test_a_phase_with_an_artifact_is_skipped(db, monkeypatch, work_dir):
    """A run that died in phase 3 must not re-download 13 GB to get there."""
    await _run(db, monkeypatch, work_dir)
    assert sorted(path.name for path in work_dir.iterdir()) == [
        seed.AUTHORS_FILE,
        seed.COUNTS_FILE,
        seed.SELECTED_FILE,
        seed.WORKS_FILE,
    ]

    # A second full run with a stream that explodes on contact: every download
    # phase must be skipped, and only the (idempotent) write phase runs.
    summary = await _run(db, monkeypatch, work_dir, stream=_exploding_stream)

    assert "reading-log" not in summary
    assert "editions" not in summary
    assert summary["load"]["synced"] == 4


async def test_force_redoes_a_phase_with_an_artifact(db, monkeypatch, work_dir):
    await _run(db, monkeypatch, work_dir, phase="reading-log")
    summary = await _run(db, monkeypatch, work_dir, phase="reading-log", force=True)
    assert summary["reading-log"]["whitelist"] == 8


async def test_artifacts_are_written_atomically(db, monkeypatch, work_dir):
    """A killed run leaves a .tmp, never a half artifact the next run trusts."""
    boom = iter(fx.reading_log_lines())

    def exploding_lines():
        yield from boom
        raise RuntimeError("killed mid-write")

    _patched(db, monkeypatch)
    with pytest.raises(RuntimeError):
        seed._write_atomic(work_dir / seed.COUNTS_FILE, exploding_lines())

    assert not (work_dir / seed.COUNTS_FILE).exists()
    assert (work_dir / (seed.COUNTS_FILE + ".tmp")).exists()


# ── Exit codes ───────────────────────────────────────────────────────────────


def test_exit_code_is_zero_on_a_clean_run():
    assert (
        seed._exit_code(
            {"load": {"synced": 4, "errors": 0, "people_errors": 0, "skipped_links": 0}}
        )
        == 0
    )


@pytest.mark.parametrize(
    "load",
    [
        {"synced": 0, "errors": 0, "people_errors": 0, "skipped_links": 0},
        {"synced": 4, "errors": 1, "people_errors": 0, "skipped_links": 0},
        {"synced": 4, "errors": 0, "people_errors": 1, "skipped_links": 0},
        {"synced": 4, "errors": 0, "people_errors": 0, "skipped_links": 1},
    ],
)
def test_exit_code_is_two_when_the_catalog_is_incomplete(load):
    """A partial catalog must not be reported as a green run."""
    assert seed._exit_code({"load": load}) == 2


def test_exit_code_is_zero_when_only_a_download_phase_was_requested():
    assert seed._exit_code({"reading-log": {"whitelist": 8}}) == 0


# ── The degraded run: the three counters and the exit code ───────────────────
#
# These are the only channel of information an unattended 1-2 h Actions run
# has. Asserting `== 0` on the happy path does not hold them: a hardcoded 0
# satisfies that just as well, which is how issue #22 stayed invisible during
# seeding. So each counter is driven off zero by a real degradation, and the
# same run is pushed through ``main()`` to prove exit code 2 comes out.


def _poison_mapper(monkeypatch, work_id: str) -> None:
    """Make ``book_to_dict`` blow up for exactly one work, as if the dump lied."""
    original = seed._ol_client.book_to_dict

    def exploding(search_doc, work_detail=None):
        if search_doc.get("key") == f"/works/{work_id}":
            raise ValueError("poisoned work: unmappable payload")
        return original(search_doc, work_detail)

    monkeypatch.setattr(seed._ol_client, "book_to_dict", exploding)


async def test_a_work_that_cannot_be_mapped_costs_only_that_work(db, monkeypatch, work_dir):
    """One unmappable work must not take the other three — nor the 2 h behind them.

    ``sync_books`` has always wrapped its own mapping step for this reason
    (issue #17 was a hand-built search doc losing a field); the dump path
    starts from 17,5 GB of third-party data, so it needs the same net.
    """
    _patched(db, monkeypatch)
    _poison_mapper(monkeypatch, fx.WORK_LOVE_HYPOTHESIS)

    summary = await seed.run(work_dir, None, False)

    assert summary["load"]["errors"] == 1
    assert summary["load"]["synced"] == 3  # the other three still landed
    assert seed._exit_code(summary) == 2

    # The poisoned work has no row and no link; the rest of the slice does.
    assert (
        await db.execute(
            select(func.count())
            .select_from(ExternalId)
            .where(ExternalId.external_id == fx.WORK_LOVE_HYPOTHESIS)
        )
    ).scalar_one() == 0
    assert (
        await db.execute(
            select(func.count())
            .select_from(ExternalId)
            .where(ExternalId.external_id == fx.WORK_CANT_HURT_ME)
        )
    ).scalar_one() == 1


async def test_a_rejected_credit_is_counted_and_never_costs_the_book(db, monkeypatch, work_dir):
    """``people_errors`` has to move when a credit is dropped, and only then."""
    _patched(db, monkeypatch)
    original = seed.author_rows

    def broken_rows(author_ids, names):
        rows = original(author_ids, names)
        # An incomplete person payload: the batch loader drops it and counts
        # it in people_rejected, which is what BatchWriter.people_errors is.
        return [replace(row, slug="") for row in rows]

    monkeypatch.setattr(seed, "author_rows", broken_rows)

    summary = await seed.run(work_dir, None, False)

    assert summary["load"]["people_errors"] > 0
    assert summary["load"]["synced"] == 4  # the books are all there
    assert summary["load"]["errors"] == 0
    assert seed._exit_code(summary) == 2
    assert (await db.execute(select(func.count()).select_from(Credit))).scalar_one() == 0


async def test_an_external_id_that_cannot_be_linked_is_reported(db, monkeypatch, work_dir):
    """``skipped_links`` is the issue-#22 channel: a lost link must be visible.

    The realistic shape, not a contrived one: an older row already holds
    ``(BOOK, OPEN_LIBRARY, OL24178205W)`` under a different slug — a title
    that changed between two seedings. The new row is written and simply
    cannot take the id.
    """
    stale = Book(
        title="Dump Seed Stale Title",
        slug="dump-seed-stale-title-2021",
        last_synced_at=datetime.now(UTC),
    )
    db.add(stale)
    await db.flush()
    await upsert_external_id(db, "BOOK", stale.id, "OPEN_LIBRARY", fx.WORK_LOVE_HYPOTHESIS)
    await db.flush()

    _patched(db, monkeypatch)
    summary = await seed.run(work_dir, None, False)

    assert summary["load"]["skipped_links"] == 1
    assert summary["load"]["synced"] == 4
    assert seed._exit_code(summary) == 2

    # The stale row keeps the id, the fresh row exists and is unlinked.
    holder = (
        await db.execute(
            select(ExternalId.item_id).where(
                ExternalId.item_type == "BOOK",
                ExternalId.external_id == fx.WORK_LOVE_HYPOTHESIS,
            )
        )
    ).scalar_one()
    assert holder == stale.id


class _LogCapture(logging.Handler):
    """Own capture handler: the suite's logging state is shared and mutable.

    ``caplog`` proved unreliable here because other modules leave loggers
    disabled (see the fixture in ``tests/test_observability.py``), and the
    point of this test is precisely that the operator *gets told*.
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_main_turns_a_degraded_summary_into_exit_2(monkeypatch):
    """The last link of the chain: ``run`` -> summary -> ``_exit_code`` -> exit.

    Driven with a fake ``run`` because ``main`` owns the event loop
    (``asyncio.run``) and cannot be called from inside one. The other half —
    that a real degraded run *produces* such a summary — is what the three
    tests above assert against the database.
    """

    async def fake_run(work_dir, only, force):
        return {"load": {"synced": 4, "errors": 1, "people_errors": 0, "skipped_links": 0}}

    monkeypatch.setattr(seed, "run", fake_run)

    handler = _LogCapture()
    handler.setLevel(logging.ERROR)
    seed.logger.addHandler(handler)
    seed.logger.disabled = False
    try:
        assert seed.main(["--work-dir", "/tmp/does-not-matter"]) == 2
    finally:
        seed.logger.removeHandler(handler)

    assert any("DEGRADED" in message for message in handler.messages)


def test_main_returns_0_on_a_clean_summary(monkeypatch):
    async def fake_run(work_dir, only, force):
        return {"load": {"synced": 4, "errors": 0, "people_errors": 0, "skipped_links": 0}}

    monkeypatch.setattr(seed, "run", fake_run)

    assert seed.main(["--work-dir", "/tmp/does-not-matter"]) == 0


def test_main_returns_1_when_the_run_blows_up(monkeypatch):
    """An unrecoverable failure (network, dump format, DB) is exit 1, not 2."""

    async def exploding_run(work_dir, only, force):
        raise RuntimeError("archive.org reset the connection")

    monkeypatch.setattr(seed, "run", exploding_run)

    assert seed.main(["--work-dir", "/tmp/does-not-matter"]) == 1


# ── The rest of the write phase, pinned ──────────────────────────────────────


async def test_a_work_with_no_title_is_dropped_and_counted(db, monkeypatch, work_dir):
    """A row with no display name is worse than a row fewer, so it is dropped.

    Not the same case as issue #18: a title that *folds* to nothing still gets
    a slug from the OL id and is seeded. This is a work whose record carries
    no title at all.
    """
    _patched(db, monkeypatch)
    await seed.run(work_dir, "reading-log", False)
    await seed.run(work_dir, "editions", False)
    await seed.run(work_dir, "works", False)
    await seed.run(work_dir, "authors", False)

    records = seed.load_work_records(work_dir)
    untitled_id = fx.WORK_CANT_HURT_ME
    records[untitled_id] = replace(records[untitled_id], title="")
    monkeypatch.setattr(seed, "load_work_records", lambda _: records)

    summary = await seed.run(work_dir, "load", False)

    assert summary["load"]["untitled"] == 1
    assert summary["load"]["synced"] == 3
    assert (
        await db.execute(
            select(func.count())
            .select_from(ExternalId)
            .where(ExternalId.external_id == untitled_id)
        )
    ).scalar_one() == 0


async def test_seeded_books_carry_the_synopsis_from_the_works_dump(db, monkeypatch, work_dir):
    """The ``overview`` the nightly search.json path cannot afford.

    ``sync_books`` calls ``book_to_dict`` with ``work_detail=None`` to save one
    HTTP request per book, so seeded rows had no synopsis. In the dumps the
    description costs nothing. The report presents this as a deliberate
    improvement, so it is asserted where it matters: in the database.
    """
    _patched(db, monkeypatch)
    await seed.run(work_dir, None, False)

    link = (
        await db.execute(
            select(ExternalId).where(
                ExternalId.item_type == "BOOK",
                ExternalId.external_id == fx.WORK_CANT_HURT_ME,
            )
        )
    ).scalar_one()
    book = (await db.execute(select(Book).where(Book.id == link.item_id))).scalar_one()

    assert book.overview and len(book.overview) > 50


async def test_the_load_phase_refreshes_the_search_view(db, monkeypatch, work_dir):
    """19 k new rows are invisible to /search until catalog_search is refreshed."""
    _patched(db, monkeypatch)
    refresh = AsyncMock()
    monkeypatch.setattr(seed, "refresh_catalog_search", refresh)

    await seed.run(work_dir, None, False)

    refresh.assert_awaited_once()


async def test_phase_selects_only_the_requested_phase(db, monkeypatch, work_dir):
    """``--phase`` must actually restrict the run, not just decorate the log."""
    _patched(db, monkeypatch)

    summary = await seed.run(work_dir, "reading-log", False)

    assert set(summary) == {"work_dir", "reading-log"}
    assert (work_dir / seed.COUNTS_FILE).exists()
    assert not (work_dir / seed.SELECTED_FILE).exists()
    assert (await db.execute(select(func.count()).select_from(Book))).scalar_one() == 0
