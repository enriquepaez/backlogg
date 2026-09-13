"""Tests for the nightly book lane after issue #27 — refresh rotation.

``sync_books`` used to page Open Library's filtered search by offset, with a
persisted cursor and ``SEED_TOP_N_BOOKS`` as its wraparound target.  Both are
gone.  Books are seeded and kept current from the monthly dumps
(features 87 and 88), so the nightly slice has nothing to discover: its work
list is the catalog rows with the oldest ``last_synced_at``, the same rotation
movies and series got in feature 86 and games in feature 90.

Covers:

1. **The work list** — ``get_stale_catalog_external_ids`` ordered by
   ``last_synced_at``, sized by ``SYNC_SLICE_SIZE_BOOKS`` (with an explicit
   ``slice_size`` winning), and chunked into ``get_works_by_ids`` requests.
2. **No data is lost by refreshing** — the row is rewritten from the *search
   doc* (isbn, cover, classifications) plus the *work detail* (description).
   A book whose work detail cannot be read is skipped rather than written
   without it, because ``ON CONFLICT DO UPDATE`` would blank the column.
3. **Nothing is evicted** — an id Open Library no longer answers for keeps its
   row: users have library entries and ratings pointing at it.
4. **Failure accounting** — a chunk that fails is one error and the next chunk
   still runs; a work detail that fails is an ``errors`` (nothing was written)
   and never a ``people_errors``; an author fetch that fails *is* a
   ``people_errors``, and the book is still written.
5. **The cursor is gone** — no offset survives anywhere in the job's result or
   in its module, and there is no ``SEED_TOP_N_BOOKS`` left to read.

Open Library is always mocked, so no test touches the network.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select

from backlogg.books.models import Book
from backlogg.core.config import settings
from backlogg.scheduler import jobs as sync_jobs
from backlogg.shared.external_ids import upsert_external_id

_NOW = datetime(2026, 9, 13, tzinfo=UTC)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _session_factory(session):
    """Session factory whose context manager always yields ``session``."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


async def _catalog_book(db, external_id: str, *, title: str, age_days: int, **columns) -> Book:
    """A book in the catalog, linked to ``external_id``, synced ``age_days`` ago."""
    book = Book(
        title=title,
        slug=title.lower().replace(" ", "-"),
        last_synced_at=_NOW - timedelta(days=age_days),
        **columns,
    )
    db.add(book)
    await db.flush()
    await upsert_external_id(db, "BOOK", book.id, "OPEN_LIBRARY", external_id)
    await db.commit()
    return book


def _search_doc(external_id: str, title: str, **overrides) -> dict:
    """The ``search.json`` doc shape ``get_works_by_ids`` returns."""
    doc = {
        "key": f"/works/{external_id}",
        "title": title,
        "first_publish_year": 1999,
        "cover_i": 4242,
        "author_name": ["Refresh Author"],
        "isbn": ["9780000000001"],
        "ddc": [],
        "lcc": [],
        "subject_facet": [],
    }
    doc.update(overrides)
    return doc


def _adapter_patches(docs, work_detail=None, **overrides):
    """Patch the three Open Library calls a refresh slice makes."""
    detail = {"description": "Refreshed synopsis."} if work_detail is None else work_detail
    return (
        patch.object(
            sync_jobs._ol_client,
            "get_works_by_ids",
            new_callable=AsyncMock,
            return_value=docs,
            **overrides,
        ),
        patch.object(
            sync_jobs._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            return_value=detail,
        ),
        patch(
            "backlogg.scheduler.jobs.collect_book_authors",
            new_callable=AsyncMock,
            return_value=[],
        ),
    )


# ── 1. The work list ─────────────────────────────────────────────────────────


async def test_the_work_list_is_the_least_recently_synced_books(db, monkeypatch):
    """The slice takes the oldest ``last_synced_at`` first, never the fresh rows."""
    monkeypatch.setattr(settings, "SYNC_SLICE_SIZE_BOOKS", 2)
    await _catalog_book(db, "OL27001W", title="Rotation Fresh", age_days=1)
    await _catalog_book(db, "OL27002W", title="Rotation Oldest", age_days=400)
    await _catalog_book(db, "OL27003W", title="Rotation Middle", age_days=200)

    by_ids, detail, authors = _adapter_patches([])
    with (
        by_ids as mock_by_ids,
        detail,
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    mock_by_ids.assert_awaited_once_with(["OL27002W", "OL27003W"])
    assert result["refreshed"] == 2
    assert result["errors"] == 0


async def test_an_explicit_slice_size_wins_over_the_setting(db, monkeypatch):
    """``scripts/backfill_sync.py`` passes a bigger slice without touching config."""
    monkeypatch.setattr(settings, "SYNC_SLICE_SIZE_BOOKS", 1)
    await _catalog_book(db, "OL27011W", title="Explicit Slice A", age_days=300)
    await _catalog_book(db, "OL27012W", title="Explicit Slice B", age_days=200)

    by_ids, detail, authors = _adapter_patches([])
    with (
        by_ids as mock_by_ids,
        detail,
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        await sync_jobs.sync_books(slice_size=2)

    assert mock_by_ids.await_args.args[0] == ["OL27011W", "OL27012W"]


async def test_the_work_list_is_chunked_into_batch_requests(db, monkeypatch):
    """Ids travel in batches: one search request per ``OL_WORKS_BY_ID_CHUNK``."""
    monkeypatch.setattr(sync_jobs, "OL_WORKS_BY_ID_CHUNK", 2)
    monkeypatch.setattr(settings, "SYNC_SLICE_SIZE_BOOKS", 3)
    for index in range(3):
        await _catalog_book(
            db, f"OL2702{index}W", title=f"Chunked Book {index}", age_days=300 - index
        )

    by_ids, detail, authors = _adapter_patches([])
    with (
        by_ids as mock_by_ids,
        detail,
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        await sync_jobs.sync_books()

    assert [call.args[0] for call in mock_by_ids.await_args_list] == [
        ["OL27020W", "OL27021W"],
        ["OL27022W"],
    ]


async def test_an_empty_catalog_asks_open_library_nothing(db):
    """Nothing to refresh is a clean no-op, not an error."""
    by_ids, detail, authors = _adapter_patches([])
    with (
        by_ids as mock_by_ids,
        detail,
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    mock_by_ids.assert_not_awaited()
    assert result == {
        "synced": 0,
        "errors": 0,
        "people_errors": 0,
        "skipped_links": 0,
        "skipped_identities": 0,
        "duration_s": result["duration_s"],
        "refreshed": 0,
    }


# ── 2. A refresh must not degrade the row ────────────────────────────────────


async def test_the_refresh_rewrites_the_row_from_the_search_doc_and_the_detail(db):
    """The search doc carries isbn/cover, the work detail carries the description.

    Both halves matter: ``book_to_dict`` reads ``isbn``/``cover_i``/``ddc``/
    ``lcc``/``subject_facet`` from the search doc and ``description`` from the
    work detail, and the batch upsert overwrites every column it is given.  A
    refresh built from either half alone would blank the other's columns
    catalog-wide.
    """
    await _catalog_book(
        db,
        "OL27031W",
        title="Refresh Target",
        age_days=400,
        overview="Stale synopsis.",
        isbn=None,
    )

    by_ids, detail, authors = _adapter_patches(
        [_search_doc("OL27031W", "Refresh Target")],
        work_detail={"description": "Refreshed synopsis."},
    )
    with (
        by_ids,
        detail,
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    assert result["synced"] == 1
    assert result["errors"] == 0

    refreshed = (await db.execute(select(Book).where(Book.title == "Refresh Target"))).scalar_one()
    assert refreshed.overview == "Refreshed synopsis."
    assert refreshed.isbn == "9780000000001"
    assert refreshed.poster_url is not None
    assert refreshed.last_synced_at > _NOW - timedelta(days=400)


async def test_a_book_whose_work_detail_fails_is_not_rewritten(db):
    """Skipping beats degrading: the row keeps its description and its place.

    ``last_synced_at`` is not stamped either, so the book stays at the head of
    the rotation and is retried on the next run.
    """
    await _catalog_book(
        db,
        "OL27041W",
        title="Detail Failure",
        age_days=400,
        overview="Synopsis worth keeping.",
    )
    stale_at = (
        await db.execute(select(Book.last_synced_at).where(Book.title == "Detail Failure"))
    ).scalar_one()

    by_ids, _, authors = _adapter_patches([_search_doc("OL27041W", "Detail Failure")])
    with (
        by_ids,
        patch.object(
            sync_jobs._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            side_effect=RuntimeError("open library down"),
        ),
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    assert result["synced"] == 0
    assert result["errors"] == 1
    assert result["people_errors"] == 0

    kept = (await db.execute(select(Book).where(Book.title == "Detail Failure"))).scalar_one()
    assert kept.overview == "Synopsis worth keeping."
    assert kept.last_synced_at == stale_at


async def test_a_work_detail_that_is_gone_leaves_the_row_alone(db):
    """A 404 on the work detail is not a reason to delete or blank a catalog row."""
    await _catalog_book(db, "OL27051W", title="Detail Gone", age_days=400, overview="Still here.")

    by_ids, _, authors = _adapter_patches([_search_doc("OL27051W", "Detail Gone")])
    with (
        by_ids,
        patch.object(
            sync_jobs._ol_client, "get_work_detail", new_callable=AsyncMock, return_value=None
        ),
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    assert result["synced"] == 0
    assert result["errors"] == 0  # a work that no longer exists is not a failure
    kept = (await db.execute(select(Book).where(Book.title == "Detail Gone"))).scalar_one()
    assert kept.overview == "Still here."


# ── 3. Nothing is evicted ────────────────────────────────────────────────────


async def test_an_id_open_library_does_not_answer_for_keeps_its_row(db, monkeypatch):
    """The batch answer omits merged/deleted works — that must not delete them.

    Users have library entries, ratings and reviews pointing at the row, so a
    nightly refresh is not the place to evict it.  The rest of the batch is
    written normally.
    """
    monkeypatch.setattr(settings, "SYNC_SLICE_SIZE_BOOKS", 2)
    await _catalog_book(db, "OL27061W", title="Answered Book", age_days=400)
    await _catalog_book(db, "OL27062W", title="Vanished Book", age_days=300)

    by_ids, detail, authors = _adapter_patches([_search_doc("OL27061W", "Answered Book")])
    with (
        by_ids,
        detail,
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    assert result["synced"] == 1
    assert result["errors"] == 0
    survivors = (
        await db.execute(select(func.count()).select_from(Book).where(Book.title.like("% Book")))
    ).scalar_one()
    assert survivors == 2


# ── 4. Failure accounting ────────────────────────────────────────────────────


async def test_a_failed_chunk_is_one_error_and_the_next_chunk_still_runs(db, monkeypatch):
    """The chunk is the unit of work that failed — not each of its ids."""
    monkeypatch.setattr(sync_jobs, "OL_WORKS_BY_ID_CHUNK", 1)
    monkeypatch.setattr(settings, "SYNC_SLICE_SIZE_BOOKS", 2)
    await _catalog_book(db, "OL27071W", title="Failing Chunk", age_days=400)
    await _catalog_book(db, "OL27072W", title="Surviving Chunk", age_days=300)

    by_ids, detail, authors = _adapter_patches(
        None,
        side_effect=[
            RuntimeError("open library down"),
            [_search_doc("OL27072W", "Surviving Chunk")],
        ],
    )
    with (
        by_ids,
        detail,
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    assert result["errors"] == 1
    assert result["synced"] == 1


async def test_an_author_failure_still_writes_the_book(db):
    """A missing credit must not cost the item: it is counted apart."""
    await _catalog_book(db, "OL27081W", title="Author Failure", age_days=400)

    by_ids, detail, _ = _adapter_patches([_search_doc("OL27081W", "Author Failure")])
    with (
        by_ids,
        detail,
        patch(
            "backlogg.scheduler.jobs.collect_book_authors",
            new_callable=AsyncMock,
            side_effect=RuntimeError("authors API down"),
        ),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    assert result["synced"] == 1
    assert result["errors"] == 0
    assert result["people_errors"] == 1


async def test_a_work_detail_timeout_is_an_error_and_never_a_people_error(db, monkeypatch):
    """The two counters must not be confused: they answer different questions.

    ``people_errors`` means "the item is in the catalog, its credits are not" —
    the one number an operator reads to decide whether a slice left authors
    behind.  A timeout reaching Open Library means the opposite: nothing was
    written at all, the row keeps its old ``last_synced_at`` and the next run
    picks it up first.  Booking it as ``people_errors`` (the shape this run
    used to report: ``synced=1, errors=0, people_errors=2`` for two timeouts)
    described two books that lost their authors, which had not happened.

    Both failures happen in the same slice here so neither counter can absorb
    the other's case.
    """
    monkeypatch.setattr(settings, "SYNC_SLICE_SIZE_BOOKS", 2)
    await _catalog_book(db, "OL27101W", title="Timed Out Book", age_days=400)
    await _catalog_book(db, "OL27102W", title="Authorless Book", age_days=300)

    by_ids, _, _ = _adapter_patches(
        [
            _search_doc("OL27101W", "Timed Out Book"),
            _search_doc("OL27102W", "Authorless Book"),
        ]
    )
    with (
        by_ids,
        patch.object(
            sync_jobs._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            side_effect=[
                TimeoutError("open library timed out"),
                {"description": "Refreshed synopsis."},
            ],
        ),
        patch(
            "backlogg.scheduler.jobs.collect_book_authors",
            new_callable=AsyncMock,
            side_effect=RuntimeError("authors API down"),
        ),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    # The unreachable book: counted as an error, not as a lost author.
    assert result["errors"] == 1
    # The written book: its authors failed, and that is the only people_error.
    assert result["people_errors"] == 1
    assert result["synced"] == 1

    timed_out = (await db.execute(select(Book).where(Book.title == "Timed Out Book"))).scalar_one()
    assert timed_out.last_synced_at == _NOW - timedelta(days=400)


async def test_an_unreadable_work_list_is_reported_as_one_error(db):
    """A database failure must not look like an empty, healthy catalog."""
    with (
        patch(
            "backlogg.scheduler.jobs.get_stale_catalog_external_ids",
            new_callable=AsyncMock,
            side_effect=RuntimeError("database down"),
        ),
        patch.object(sync_jobs._ol_client, "get_works_by_ids", new_callable=AsyncMock) as mock_ol,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    mock_ol.assert_not_awaited()
    assert result["errors"] == 1
    assert result["synced"] == 0


# ── 5. The cursor is gone ────────────────────────────────────────────────────


async def test_sync_books_has_no_cursor_left(db):
    """Books were the last cursor reader (issue #27).

    Asserted on the module: ``scheduler.jobs`` does not import
    ``get_sync_offset``/``set_sync_offset`` at all any more — those functions
    no longer exist — so there is nothing left in the job to patch, which is a
    stronger statement than "not called".
    """
    assert not hasattr(sync_jobs, "get_sync_offset")
    assert not hasattr(sync_jobs, "set_sync_offset")
    assert not hasattr(settings, "SEED_TOP_N_BOOKS")

    await _catalog_book(db, "OL27091W", title="Cursorless Book", age_days=400)

    by_ids, detail, authors = _adapter_patches([_search_doc("OL27091W", "Cursorless Book")])
    with (
        by_ids,
        detail,
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    assert result["synced"] == 1
    assert "offset" not in result


@pytest.mark.parametrize("key", ["pending", "stuck"])
async def test_the_result_reports_no_target_progress(db, key):
    """Books have no ``seed_targets``: reporting ``pending: 0`` would tell the
    backfill loop that a catalog this lane never seeds is complete."""
    by_ids, detail, authors = _adapter_patches([])
    with (
        by_ids,
        detail,
        authors,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_books()

    assert key not in result
