"""Tests for feature 85 — backfill_credits_targeted (issue #15).

What is under test:

- ``scheduler.repository.get_credit_gaps`` returns **exactly** the catalog
  items that have no credits: items that already have one are out, items
  already stamped with ``credits_synced_at`` are out, ``--recheck`` brings
  the stamped ones back, and an item with no ``external_ids`` row is
  reported as skipped instead of raising;
- ``scheduler.jobs.sync_missing_credits`` fetches one endpoint per item (no
  item detail re-fetch, no item re-write), stamps ``credits_synced_at``
  after a successful fetch **with or without credits**, leaves it NULL and
  counts ``people_errors`` after a failed one, never touches
  ``sync_cursors``, and persists series creators from ``created_by``;
- ``scripts/backfill_sync.py`` exposes the mode, rejects ``game``, and
  propagates ``people_errors`` to the summary of ``run_backfill`` — the
  observability bug that made a run with 100% credit failures report
  "6000 synced, 0 errors".

The gap query and the write path run against the real PostgreSQL test
database (they are SQL, a mock would test nothing).  Every external API call
is mocked — no network.
"""

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from backlogg.books.models import Book
from backlogg.movies import service as movies_service
from backlogg.movies.models import Movie
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import get_credit_gaps
from backlogg.series.models import Series
from backlogg.shared.external_ids import ExternalId
from backlogg.shared.models import Credit, Person

# ── Load the script as a module (scripts/ is not an installed package) ───────

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "backfill_sync.py"
_spec = importlib.util.spec_from_file_location("backfill_sync_targeted", _SCRIPT_PATH)
backfill_sync = importlib.util.module_from_spec(_spec)
sys.modules["backfill_sync_targeted"] = backfill_sync
_spec.loader.exec_module(backfill_sync)


# ── Fixtures/helpers ─────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


async def _add_movie(db, slug: str, *, credits_synced_at: datetime | None = None) -> Movie:
    movie = Movie(
        title=slug.replace("-", " ").title(),
        slug=slug,
        last_synced_at=_now(),
        credits_synced_at=credits_synced_at,
    )
    db.add(movie)
    await db.flush()
    return movie


async def _add_series(db, slug: str) -> Series:
    series = Series(title=slug.replace("-", " ").title(), slug=slug, last_synced_at=_now())
    db.add(series)
    await db.flush()
    return series


async def _add_book(db, slug: str) -> Book:
    book = Book(title=slug.replace("-", " ").title(), slug=slug, last_synced_at=_now())
    db.add(book)
    await db.flush()
    return book


async def _link(db, item_type: str, item_id: int, source: str, external_id: str) -> None:
    db.add(ExternalId(item_type=item_type, item_id=item_id, source=source, external_id=external_id))
    await db.flush()


async def _add_credit(db, item_type: str, item_id: int, person_slug: str) -> None:
    person = Person(name=person_slug, slug=person_slug, last_synced_at=_now())
    db.add(person)
    await db.flush()
    db.add(Credit(item_type=item_type, item_id=item_id, person_id=person.id, role="ACTOR"))
    await db.flush()


def _session_factory(db):
    """A stand-in for ``async_session_factory`` yielding the test session.

    Keeps the job inside the fixture's SAVEPOINT, so its commits are undone
    at teardown like every other test's writes.
    """
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _tmdb_person(tmdb_id: int, name: str, order: int = 0) -> dict:
    return {
        "id": tmdb_id,
        "name": name,
        "profile_path": None,
        "order": order,
        "character": f"{name} the character",
    }


# ── The gap query returns exactly the gap ────────────────────────────────────


async def test_gap_query_returns_exactly_the_items_without_credits(db):
    """Items with credits and items already stamped are out; the rest are in."""
    missing = await _add_movie(db, "gap-missing-credits")
    covered = await _add_movie(db, "gap-has-credits")
    stamped = await _add_movie(db, "gap-already-stamped", credits_synced_at=_now())
    await _link(db, "MOVIE", missing.id, "TMDB", "gap-tmdb-1")
    await _link(db, "MOVIE", covered.id, "TMDB", "gap-tmdb-2")
    await _link(db, "MOVIE", stamped.id, "TMDB", "gap-tmdb-3")
    await _add_credit(db, "MOVIE", covered.id, "gap-person-1")

    result = await get_credit_gaps(db, "MOVIE")

    assert [gap.item_id for gap in result.gaps] == [missing.id]
    assert result.gaps[0].external_id == "gap-tmdb-1"
    assert result.skipped_no_external_id == 0
    assert result.considered == 1


async def test_gap_query_recheck_includes_already_stamped_items(db):
    """--recheck ignores credits_synced_at and sweeps the stamped items again."""
    missing = await _add_movie(db, "recheck-missing")
    stamped = await _add_movie(db, "recheck-stamped", credits_synced_at=_now())
    covered = await _add_movie(db, "recheck-covered")
    await _link(db, "MOVIE", missing.id, "TMDB", "recheck-tmdb-1")
    await _link(db, "MOVIE", stamped.id, "TMDB", "recheck-tmdb-2")
    await _link(db, "MOVIE", covered.id, "TMDB", "recheck-tmdb-3")
    await _add_credit(db, "MOVIE", covered.id, "recheck-person-1")

    default = await get_credit_gaps(db, "MOVIE")
    rechecked = await get_credit_gaps(db, "MOVIE", recheck=True)

    assert [gap.item_id for gap in default.gaps] == [missing.id]
    # The item with credits stays out either way: --recheck relaxes the stamp,
    # not the "has no credits" predicate.
    assert [gap.item_id for gap in rechecked.gaps] == sorted([missing.id, stamped.id])


async def test_gap_query_reports_items_without_external_id_as_skipped(db):
    """An unlinked item cannot be worked on — counted, never raised on."""
    workable = await _add_series(db, "skip-workable")
    unlinked = await _add_series(db, "skip-unlinked")
    await _link(db, "SERIES", workable.id, "TMDB", "skip-tmdb-1")

    result = await get_credit_gaps(db, "SERIES")

    assert [gap.item_id for gap in result.gaps] == [workable.id]
    assert result.skipped_no_external_id == 1
    assert result.considered == 2
    assert unlinked.id not in [gap.item_id for gap in result.gaps]


async def test_gap_query_matches_the_source_of_the_type(db):
    """A book is joined against OPEN_LIBRARY, not against TMDB."""
    book = await _add_book(db, "gap-book-openlibrary")
    await _link(db, "BOOK", book.id, "OPEN_LIBRARY", "OL85W")
    wrong_source = await _add_book(db, "gap-book-wrong-source")
    await _link(db, "BOOK", wrong_source.id, "TMDB", "gap-book-tmdb-id")

    result = await get_credit_gaps(db, "BOOK")

    assert [gap.external_id for gap in result.gaps] == ["OL85W"]
    assert result.skipped_no_external_id == 1


# ── The targeted job ─────────────────────────────────────────────────────────


async def test_targeted_mode_fetches_only_credits_and_writes_them(db):
    """One HTTP call per item, no detail re-fetch, credits persisted, item stamped."""
    movie = await _add_movie(db, "targeted-movie-with-credits")
    await _link(db, "MOVIE", movie.id, "TMDB", "770001")

    credits_payload = {
        "cast": [_tmdb_person(9001, "Targeted Actor")],
        "crew": [
            {"id": 9002, "name": "Targeted Director", "job": "Director", "profile_path": None}
        ],
    }

    with (
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
        patch.object(
            movies_service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value=credits_payload,
        ) as mock_credits,
        patch.object(movies_service._tmdb, "get_movie_detail", new_callable=AsyncMock) as detail,
        patch.object(sync_jobs, "set_sync_offset", new_callable=AsyncMock) as mock_cursor,
    ):
        summary = await sync_jobs.sync_missing_credits("movie")

    # The external id of the local row is what gets fetched — resolved by the
    # gap query, not guessed from a popularity ranking.
    mock_credits.assert_awaited_once_with(770001)
    detail.assert_not_awaited()  # the row already exists — never re-fetched
    mock_cursor.assert_not_awaited()  # targeted mode does not touch sync_cursors

    roles = (
        (
            await db.execute(
                select(Credit.role).where(Credit.item_type == "MOVIE", Credit.item_id == movie.id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(roles) == ["ACTOR", "DIRECTOR"]

    refreshed = await db.get(Movie, movie.id, populate_existing=True)
    assert refreshed.credits_synced_at is not None
    assert summary["processed"] == 1
    assert summary["with_credits"] == 1
    assert summary["credits_written"] == 2
    assert summary["people_errors"] == 0
    assert summary["stop_reason"] == "exhausted"


async def test_item_with_zero_credits_is_still_stamped(db):
    """An empty credits payload is a *successful* fetch: stamp it, never retry."""
    movie = await _add_movie(db, "targeted-movie-no-credits")
    await _link(db, "MOVIE", movie.id, "TMDB", "770002")

    with (
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
        patch.object(
            movies_service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value={"cast": [], "crew": []},
        ),
    ):
        summary = await sync_jobs.sync_missing_credits("movie")

    refreshed = await db.get(Movie, movie.id, populate_existing=True)
    assert refreshed.credits_synced_at is not None
    assert summary["processed"] == 1
    assert summary["sealed_without_credits"] == 1
    assert summary["credits_written"] == 0
    assert summary["people_errors"] == 0

    # And it is gone from the work list of the next run.
    assert movie.id not in [gap.item_id for gap in (await get_credit_gaps(db, "MOVIE")).gaps]


async def test_failed_fetch_is_not_stamped_and_counts_as_people_error(db):
    """A fetch that raises leaves credits_synced_at NULL so the next run retries."""
    movie = await _add_movie(db, "targeted-movie-fetch-fails")
    await _link(db, "MOVIE", movie.id, "TMDB", "770003")

    with (
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
        patch.object(
            movies_service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            side_effect=RuntimeError("TMDB is down"),
        ),
    ):
        summary = await sync_jobs.sync_missing_credits("movie")

    refreshed = await db.get(Movie, movie.id, populate_existing=True)
    assert refreshed.credits_synced_at is None
    assert summary["processed"] == 0
    assert summary["people_errors"] == 1
    # Still in the work list — that is the point of not stamping it.
    assert movie.id in [gap.item_id for gap in (await get_credit_gaps(db, "MOVIE")).gaps]


async def test_item_without_external_id_does_not_break_the_run(db):
    """An unlinked item is counted as skipped; the rest of the run proceeds."""
    workable = await _add_movie(db, "targeted-linked")
    unlinked = await _add_movie(db, "targeted-unlinked")
    await _link(db, "MOVIE", workable.id, "TMDB", "770004")

    with (
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
        patch.object(
            movies_service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value={"cast": [_tmdb_person(9101, "Linked Actor")], "crew": []},
        ) as mock_credits,
    ):
        summary = await sync_jobs.sync_missing_credits("movie")

    assert mock_credits.await_count == 1  # the unlinked item was never fetched
    assert summary["skipped_no_external_id"] == 1
    assert summary["considered"] == 2
    assert summary["processed"] == 1
    assert summary["people_errors"] == 0

    still_null = await db.get(Movie, unlinked.id, populate_existing=True)
    assert still_null.credits_synced_at is None


async def test_series_creators_are_persisted_in_targeted_mode(db):
    """created_by -> CREATOR credits, from the single append_to_response call."""
    series = await _add_series(db, "targeted-series-creators")
    await _link(db, "SERIES", series.id, "TMDB", "884242")

    detail_payload = {
        "id": 884242,
        "credits": {"cast": [_tmdb_person(9201, "Series Actor")]},
        "created_by": [{"id": 9202, "name": "Series Creator", "profile_path": None}],
    }

    with (
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
        patch.object(
            sync_jobs._tmdb_series,
            "get_series_detail",
            new_callable=AsyncMock,
            return_value=detail_payload,
        ) as mock_detail,
        patch.object(sync_jobs._tmdb_series, "get_series_credits", new_callable=AsyncMock) as sep,
    ):
        summary = await sync_jobs.sync_missing_credits("series")

    mock_detail.assert_awaited_once_with(884242, append_to_response="credits")
    sep.assert_not_awaited()  # no second call: append_to_response carries the cast

    roles = (
        (
            await db.execute(
                select(Credit.role).where(Credit.item_type == "SERIES", Credit.item_id == series.id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(roles) == ["ACTOR", "CREATOR"]
    assert summary["credits_written"] == 2


async def test_targeted_mode_rejects_games():
    """games have no people credits — fail loudly instead of running empty."""
    with pytest.raises(ValueError, match="game"):
        await sync_jobs.sync_missing_credits("game")


async def test_targeted_mode_stops_on_time_budget(db):
    """An exhausted budget stops before the next chunk and says so."""
    for index in range(3):
        movie = await _add_movie(db, f"targeted-budget-{index}")
        await _link(db, "MOVIE", movie.id, "TMDB", f"77010{index}")

    with (
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
        patch.object(sync_jobs.settings, "BULK_LOAD_BATCH_SIZE", 1),
        patch.object(
            movies_service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value={"cast": [], "crew": []},
        ) as mock_credits,
    ):
        summary = await sync_jobs.sync_missing_credits("movie", time_budget_s=0)

    mock_credits.assert_not_awaited()
    assert summary["stop_reason"] == "time_budget"
    assert summary["processed"] == 0


# ── people_errors propagation (the observability bug) ────────────────────────


def _mocked_session_factory():
    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_cm)


def _job_result(
    synced: int, people_errors: int, offset: int = 0, pending: int | None = None
) -> dict:
    result = {
        "synced": synced,
        "errors": 0,
        "people_errors": people_errors,
        "offset": offset,
        "duration_s": 0.1,
    }
    if pending is not None:
        result["pending"] = pending
    return result


async def test_run_backfill_summary_reports_people_errors():
    """The default mode's summary carries people_errors instead of dropping it.

    Driven here through ``movie``, which since feature 86 loops on the
    pending-target count rather than on the cursor — the people_errors
    accumulation is the same either way.
    """
    results = [
        _job_result(synced=500, people_errors=7, pending=300),
        _job_result(synced=300, people_errors=5, pending=0),
    ]
    with (
        patch.object(backfill_sync, "get_sync_offset", new_callable=AsyncMock),
        patch.object(backfill_sync, "async_session_factory", new=_mocked_session_factory()),
        patch("backlogg.scheduler.jobs.sync_movies", new_callable=AsyncMock, side_effect=results),
    ):
        summary = await backfill_sync.run_backfill("movie", slice_size=500, time_budget_s=3600)

    assert summary["people_errors"] == 12
    assert summary["synced"] == 800
    assert summary["errors"] == 0


async def test_run_backfill_tolerates_jobs_without_people_errors():
    """sync_games reports no people_errors key — the summary must not blow up."""
    with (
        patch.object(backfill_sync, "get_sync_offset", new_callable=AsyncMock, side_effect=[0, 0]),
        patch.object(backfill_sync, "async_session_factory", new=_mocked_session_factory()),
        patch(
            "backlogg.scheduler.jobs.sync_games",
            new_callable=AsyncMock,
            return_value={"synced": 10, "errors": 0, "offset": 0, "duration_s": 0.1},
        ),
    ):
        summary = await backfill_sync.run_backfill("game", slice_size=500, time_budget_s=3600)

    assert summary["people_errors"] == 0


# ── CLI wiring ───────────────────────────────────────────────────────────────


def test_cli_only_missing_credits_runs_the_targeted_mode():
    """--only-missing-credits routes to run_credits_backfill, not to the loop."""
    summary = {
        "content_type": "series",
        "considered": 10,
        "processed": 9,
        "with_credits": 7,
        "sealed_without_credits": 2,
        "credits_written": 60,
        "people_errors": 1,
        "skipped_no_external_id": 1,
        "elapsed_s": 3.2,
        "stop_reason": "exhausted",
    }
    with (
        patch.object(
            backfill_sync, "run_credits_backfill", new_callable=AsyncMock, return_value=summary
        ) as mock_targeted,
        patch.object(backfill_sync, "run_backfill", new_callable=AsyncMock) as mock_ranking,
        patch.object(backfill_sync, "engine", new=AsyncMock()),
    ):
        code = backfill_sync.main(
            ["series", "--only-missing-credits", "--recheck", "--time-budget-minutes", "2"]
        )

    assert code == 0
    mock_ranking.assert_not_awaited()
    mock_targeted.assert_awaited_once_with("series", 120, True)


def test_cli_rejects_only_missing_credits_for_games():
    """The unsupported combo fails at parse time with a message, never silently."""
    with pytest.raises(SystemExit) as excinfo:
        backfill_sync.main(["game", "--only-missing-credits"])
    assert excinfo.value.code != 0


def test_cli_rejects_recheck_without_the_targeted_mode():
    """--recheck has no meaning in ranking mode."""
    with pytest.raises(SystemExit) as excinfo:
        backfill_sync.main(["movie", "--recheck"])
    assert excinfo.value.code != 0


async def test_run_credits_backfill_aborts_when_nothing_progressed():
    """All fetches failing is a red run, not a green one with zeros."""
    result = {
        "content_type": "movie",
        "considered": 5,
        "processed": 0,
        "with_credits": 0,
        "sealed_without_credits": 0,
        "credits_written": 0,
        "people_errors": 5,
        "skipped_no_external_id": 0,
        "duration_s": 1.0,
        "stop_reason": "exhausted",
    }
    with (
        patch.object(
            backfill_sync.jobs, "sync_missing_credits", new_callable=AsyncMock, return_value=result
        ),
        pytest.raises(backfill_sync.BackfillError),
    ):
        await backfill_sync.run_credits_backfill("movie", time_budget_s=60)
