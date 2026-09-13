"""Tests for feature 26 — direct_backfill_sync.

Covers:
- the optional ``slice_size`` override in the sync jobs (None keeps the
  settings-based behaviour, an explicit value takes precedence);
- IGDB pagination beyond 500 items with throttling between pages;
- the backfill loop in ``scripts/backfill_sync.py``: multiple iterations,
  stop on an exhausted target list (movie/series/game, features 86 and 90)
  even when part of that list is permanently stuck, stop on time budget —
  which is the *only* stop a ``book`` run has, its loop being the refresh
  rotation since issue #27 — abort on an iteration with zero progress, and
  CLI exit codes;
- error propagation from a failing adapter fetch: ``sync_books`` reports
  ``errors=1``, and the backfill guard turns that into a ``BackfillError``
  (red run) instead of a silent green one.

⚠️ No cursor is read anywhere here any more: books were the last type with a
persisted offset and left it in issue #27.

Everything external (adapters, jobs, DB sessions) is mocked — no real
network calls and no real database access.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import httpx
import pytest

from backlogg.games.adapters.igdb import IGDB_PAGE_THROTTLE_S, IGDBClient
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import SeedTargetProgress

# ── Load the script as a module (scripts/ is not an installed package) ───────

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "backfill_sync.py"
_spec = importlib.util.spec_from_file_location("backfill_sync", _SCRIPT_PATH)
backfill_sync = importlib.util.module_from_spec(_spec)
sys.modules["backfill_sync"] = backfill_sync
_spec.loader.exec_module(backfill_sync)


def _mocked_session_factory():
    """Return a mock session factory whose context manager yields a mock session."""
    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_cm)


# ── slice_size override in the sync jobs ─────────────────────────────────────


def _job_factory_patch():
    """Common patch for job tests: no DB."""
    return patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory())


def _book_work_list(external_ids: list[str]):
    """Patch the book refresh rotation to hand the job exactly these ids."""
    return patch(
        "backlogg.scheduler.jobs.get_stale_catalog_external_ids",
        new_callable=AsyncMock,
        return_value=external_ids,
    )


def _empty_progress() -> SeedTargetProgress:
    """A target list with nothing left to do and nothing stuck."""
    return SeedTargetProgress(total=0, pending=0, gone=0, unlinkable=0)


def _seed_work_list_patch():
    """Capture the slice size the TMDB jobs ask their work list for."""
    return patch(
        "backlogg.scheduler.jobs._read_seed_work_list",
        new_callable=AsyncMock,
        return_value=([], [], _empty_progress()),
    )


async def test_sync_movies_slice_size_overrides_setting(monkeypatch):
    """An explicit slice_size takes precedence over settings.SYNC_SLICE_SIZE.

    Movies take their slice from ``seed_targets`` since feature 86, so what
    the override controls is how many targets one iteration claims — which is
    exactly what the backfill script raises to process bigger slices.
    """
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 3)

    with (
        _seed_work_list_patch() as mock_work_list,
        _job_factory_patch(),
    ):
        result = await sync_jobs.sync_movies(slice_size=7)

    mock_work_list.assert_awaited_once_with("MOVIE", "TMDB", 7)
    assert result["errors"] == 0


async def test_sync_movies_slice_size_none_uses_setting(monkeypatch):
    """slice_size=None preserves the settings-based behaviour."""
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 3)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE_MOVIES", None)

    with (
        _seed_work_list_patch() as mock_work_list,
        _job_factory_patch(),
    ):
        await sync_jobs.sync_movies(slice_size=None)

    mock_work_list.assert_awaited_once_with("MOVIE", "TMDB", 3)


async def test_sync_books_slice_size_override_sizes_the_refresh_rotation(monkeypatch):
    """The override is what the script raises to refresh more books per iteration.

    It used to be capped by ``SEED_TOP_N_BOOKS - offset``; that ceiling went
    with the cursor (issue #27), so the override now travels straight to the
    rotation query and nothing shrinks it.
    """
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 3)

    with (
        patch(
            "backlogg.scheduler.jobs.get_stale_catalog_external_ids",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_work_list,
        _job_factory_patch(),
    ):
        await sync_jobs.sync_books(slice_size=500)

    mock_work_list.assert_awaited_once_with(ANY, "BOOK", "OPEN_LIBRARY", 500)


# ── Adapter fetch failure: errors reported, cursor untouched ─────────────────


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    response = MagicMock()
    response.status_code = status_code
    return httpx.HTTPStatusError(f"HTTP {status_code}", request=MagicMock(), response=response)


async def test_sync_books_fetch_error_reports_error_and_writes_nothing(monkeypatch):
    """An adapter exception yields errors=1 and no item written.

    The books of that chunk keep their old ``last_synced_at``, so the next run
    finds them at the head of the rotation — which is what replaced "the cursor
    is not advanced on error" as the retry guarantee.
    """
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 100)

    with (
        _book_work_list(["OL1W", "OL2W"]),
        patch.object(
            sync_jobs._ol_client,
            "get_works_by_ids",
            new_callable=AsyncMock,
            side_effect=_http_error(500),
        ),
        _job_factory_patch(),
    ):
        result = await sync_jobs.sync_books()

    assert result["synced"] == 0
    assert result["errors"] == 1


async def test_backfill_guard_aborts_on_fetch_error(monkeypatch):
    """End to end: adapter raises → real sync_books errors → BackfillError (exit 1).

    This is the regression for run 28799265814, where an OL 500 was masked
    as an empty listing and produced a false-green stop.
    """
    with (
        _book_work_list(["OL1W"]),
        patch.object(
            sync_jobs._ol_client,
            "get_works_by_ids",
            new_callable=AsyncMock,
            side_effect=_http_error(500),
        ),
        _job_factory_patch(),
        pytest.raises(backfill_sync.BackfillError),
    ):
        await backfill_sync.run_backfill("book", slice_size=500, time_budget_s=3600)


# ── IGDB pagination beyond 500 with throttling ───────────────────────────────


def _igdb_batch(start: int, count: int) -> list[dict]:
    return [{"id": i} for i in range(start, start + count)]


async def test_igdb_paginates_beyond_500_with_throttle():
    """limit > 500 issues successive requests with a sleep between pages."""
    client = IGDBClient()
    pages = [_igdb_batch(0, 500), _igdb_batch(500, 500), _igdb_batch(1000, 200)]
    with (
        patch.object(client, "_post", new_callable=AsyncMock, side_effect=pages) as mock_post,
        patch("backlogg.games.adapters.igdb.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        results = await client.get_top_games(limit=1200, offset=0)

    assert [r["id"] for r in results] == list(range(1200))
    assert mock_post.await_count == 3
    bodies = [call.args[1] for call in mock_post.await_args_list]
    assert " limit 500;" in bodies[0] and " offset 0;" in bodies[0]
    assert " limit 500;" in bodies[1] and " offset 500;" in bodies[1]
    assert " limit 200;" in bodies[2] and " offset 1000;" in bodies[2]
    # One sleep between each pair of consecutive requests (4 req/s limit)
    assert mock_sleep.await_count == 2
    for call in mock_sleep.await_args_list:
        assert call.args == (IGDB_PAGE_THROTTLE_S,)


async def test_igdb_pagination_starts_at_offset():
    """The first page starts at the requested offset, later pages advance it."""
    client = IGDBClient()
    pages = [_igdb_batch(3000, 500), _igdb_batch(3500, 100)]
    with (
        patch.object(client, "_post", new_callable=AsyncMock, side_effect=pages) as mock_post,
        patch("backlogg.games.adapters.igdb.asyncio.sleep", new_callable=AsyncMock),
    ):
        results = await client.get_top_games(limit=600, offset=3000)

    bodies = [call.args[1] for call in mock_post.await_args_list]
    assert " offset 3000;" in bodies[0]
    assert " offset 3500;" in bodies[1]
    assert " limit 100;" in bodies[1]
    assert len(results) == 600


async def test_igdb_short_page_stops_pagination():
    """A page shorter than requested ends the loop (listing exhausted)."""
    client = IGDBClient()
    pages = [_igdb_batch(0, 500), _igdb_batch(500, 120)]
    with (
        patch.object(client, "_post", new_callable=AsyncMock, side_effect=pages) as mock_post,
        patch("backlogg.games.adapters.igdb.asyncio.sleep", new_callable=AsyncMock),
    ):
        results = await client.get_top_games(limit=2000, offset=0)

    assert mock_post.await_count == 2
    assert len(results) == 620


async def test_igdb_single_page_does_not_throttle():
    """limit <= 500 keeps the single-request behaviour with no sleep."""
    client = IGDBClient()
    with (
        patch.object(
            client, "_post", new_callable=AsyncMock, return_value=_igdb_batch(0, 300)
        ) as mock_post,
        patch("backlogg.games.adapters.igdb.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        results = await client.get_top_games(limit=300, offset=100)

    mock_post.assert_awaited_once()
    body = mock_post.await_args.args[1]
    assert " limit 300;" in body and " offset 100;" in body
    mock_sleep.assert_not_awaited()
    assert len(results) == 300


# ── Backfill loop (script) ───────────────────────────────────────────────────


def _job_result(
    synced: int,
    errors: int = 0,
    pending: int | None = None,
    stuck: int | None = None,
    refreshed: int | None = None,
) -> dict:
    result = {"synced": synced, "errors": errors, "duration_s": 0.1}
    if pending is not None:
        result["pending"] = pending
        result["stuck"] = stuck or 0
    if refreshed is not None:
        result["refreshed"] = refreshed
    return result


async def test_backfill_book_loops_until_the_time_budget():
    """The book loop is the refresh rotation: only the clock ends it.

    Every iteration finds something older to re-sync — there is no "done" to
    converge on, unlike the target-driven types — so the loop must keep going
    while the budget lasts and stop on ``time_budget``, not report a false
    completion.
    """
    results = [
        _job_result(synced=500, refreshed=500),
        _job_result(synced=500, refreshed=500),
        _job_result(synced=200, errors=1, refreshed=500),
    ]
    # Start, then one reading per iteration; the third crosses the budget.
    clock = iter([0.0, 10.0, 20.0, 3601.0, 3601.0, 3601.0])

    with (
        patch(
            "backlogg.scheduler.jobs.sync_books", new_callable=AsyncMock, side_effect=results
        ) as mock_job,
        patch.object(backfill_sync.time, "monotonic", lambda: next(clock)),
    ):
        summary = await backfill_sync.run_backfill("book", slice_size=500, time_budget_s=3600)

    assert mock_job.await_count == 3
    for call in mock_job.await_args_list:
        assert call.kwargs == {"slice_size": 500}
    assert summary["stop_reason"] == "time_budget"
    assert summary["iterations"] == 3
    assert summary["synced"] == 1200
    assert summary["errors"] == 1


async def test_backfill_loops_until_the_target_list_is_exhausted():
    """For a target-driven type (feature 86) the loop runs until pending hits 0.

    No cursor is ever consulted: the stop signal is the job's own ``pending``
    count, which is a live difference against the catalog rather than a stored
    offset.
    """
    results = [
        _job_result(synced=500, pending=700),
        _job_result(synced=500, pending=200),
        _job_result(synced=200, pending=0),
    ]

    with (
        patch(
            "backlogg.scheduler.jobs.sync_movies", new_callable=AsyncMock, side_effect=results
        ) as mock_job,
    ):
        summary = await backfill_sync.run_backfill("movie", slice_size=500, time_budget_s=3600)

    assert not hasattr(backfill_sync, "get_sync_offset")
    assert mock_job.await_count == 3
    assert summary["stop_reason"] == "exhausted"
    assert summary["synced"] == 1200
    assert summary["pending"] == 0


async def test_backfill_terminates_even_with_permanently_stuck_targets():
    """Review B1: the loop must end, and ``stuck`` must reach the summary.

    ``pending`` counts *workable* targets, so the unlinkable residue retires
    out of it and the loop converges instead of re-hydrating the same items
    (which write their row, so ``synced > 0`` and the no-progress guard would
    never have fired) until the time budget expired.
    """
    results = [
        _job_result(synced=500, pending=400, stuck=0),
        _job_result(synced=400, pending=3, stuck=0),
        _job_result(synced=3, pending=0, stuck=7),
    ]
    with (
        patch(
            "backlogg.scheduler.jobs.sync_movies", new_callable=AsyncMock, side_effect=results
        ) as mock_job,
    ):
        summary = await backfill_sync.run_backfill("movie", slice_size=500, time_budget_s=3600)

    assert mock_job.await_count == 3
    assert summary["stop_reason"] == "exhausted"
    assert summary["pending"] == 0
    assert summary["stuck"] == 7


async def test_backfill_adds_up_the_skipped_links_of_every_iteration():
    """Issue #22: the seeding panel light survives the loop.

    A backfill of 118.850 items runs for hours over dozens of iterations. If
    the script read ``skipped_links`` off each job result and threw it away
    (which is exactly what it used to do with ``people_errors``), a run losing
    catalog on every single slice would still finish reporting "N synced, 0
    errors" and the loss would only be findable by hand afterwards.
    """
    results = [
        _job_result(synced=500, pending=1000) | {"skipped_links": 3},
        _job_result(synced=500, pending=500) | {"skipped_links": 0},
        _job_result(synced=200, pending=0) | {"skipped_links": 4},
    ]

    with patch("backlogg.scheduler.jobs.sync_movies", new_callable=AsyncMock, side_effect=results):
        summary = await backfill_sync.run_backfill("movie", slice_size=500, time_budget_s=3600)

    assert summary["skipped_links"] == 7


async def test_backfill_reports_zero_skipped_links_for_a_job_that_omits_the_key():
    """A job result without the key must not blow the aggregation up."""
    results = [_job_result(synced=200, pending=0)]

    with patch("backlogg.scheduler.jobs.sync_movies", new_callable=AsyncMock, side_effect=results):
        summary = await backfill_sync.run_backfill("movie", slice_size=500, time_budget_s=3600)

    assert summary["skipped_links"] == 0


async def test_backfill_does_not_treat_unknown_progress_as_done():
    """Review N1: ``pending: None`` (work list unreadable) is not "exhausted".

    The BackfillError guard fires first here, but the stop condition must not
    depend on the order of two guards — a database outage must never be able
    to end a backfill as a green, complete run.
    """
    unknown = {
        "synced": 0,
        "errors": 1,
        "people_errors": 0,
        "duration_s": 0.1,
        "pending": None,
        "stuck": None,
    }
    with (
        patch("backlogg.scheduler.jobs.sync_movies", new_callable=AsyncMock, return_value=unknown),
        pytest.raises(backfill_sync.BackfillError),
    ):
        await backfill_sync.run_backfill("movie", slice_size=500, time_budget_s=3600)


async def test_backfill_target_driven_stops_on_time_budget():
    """A target-driven run still honours the time budget with work left over."""
    with (
        patch(
            "backlogg.scheduler.jobs.sync_series",
            new_callable=AsyncMock,
            return_value=_job_result(synced=500, pending=9000),
        ) as mock_job,
    ):
        summary = await backfill_sync.run_backfill("series", slice_size=500, time_budget_s=0)

    mock_job.assert_awaited_once_with(slice_size=500)
    assert summary["stop_reason"] == "time_budget"
    assert summary["pending"] == 9000


async def test_backfill_stops_on_time_budget():
    """An exhausted time budget stops the loop with work still left."""
    with patch(
        "backlogg.scheduler.jobs.sync_books",
        new_callable=AsyncMock,
        return_value=_job_result(synced=500, refreshed=500),
    ) as mock_job:
        summary = await backfill_sync.run_backfill("book", slice_size=500, time_budget_s=0)

    mock_job.assert_awaited_once_with(slice_size=500)
    assert summary["stop_reason"] == "time_budget"
    assert summary["iterations"] == 1


async def test_backfill_book_stops_when_there_is_nothing_to_refresh():
    """An empty catalog is the one "done" a refresh rotation can report.

    Without this the loop would spin on a job that does nothing until the time
    budget expired — five hours of no-ops reported as a normal run.
    """
    with patch(
        "backlogg.scheduler.jobs.sync_books",
        new_callable=AsyncMock,
        return_value=_job_result(synced=0, refreshed=0),
    ) as mock_job:
        summary = await backfill_sync.run_backfill("book", slice_size=500, time_budget_s=3600)

    mock_job.assert_awaited_once_with(slice_size=500)
    assert summary["stop_reason"] == "exhausted"
    assert summary["iterations"] == 1
    assert summary["synced"] == 0


async def test_backfill_game_stops_on_an_exhausted_target_list():
    """Feature 90: ``game`` joins ``movie``/``series`` on the target-driven loop.

    The cursor is never read for it — which is also what makes the old
    ``seed_top_n`` dispatch argument meaningless for games — and the loop
    stops on ``pending == 0``, not on a wraparound that can no longer happen.
    """
    with (
        patch(
            "backlogg.scheduler.jobs.sync_games",
            new_callable=AsyncMock,
            return_value=_job_result(synced=500, pending=0, stuck=3),
        ) as mock_job,
    ):
        summary = await backfill_sync.run_backfill("game", slice_size=500, time_budget_s=3600)

    mock_job.assert_awaited_once_with(slice_size=500)
    assert not hasattr(backfill_sync, "get_sync_offset")
    assert summary["stop_reason"] == "exhausted"
    assert summary["pending"] == 0
    assert summary["stuck"] == 3


async def test_backfill_aborts_when_iteration_makes_no_progress():
    """An iteration with errors and zero synced items raises BackfillError."""
    with (
        patch(
            "backlogg.scheduler.jobs.sync_series",
            new_callable=AsyncMock,
            return_value=_job_result(synced=0, errors=1),
        ),
        pytest.raises(backfill_sync.BackfillError),
    ):
        await backfill_sync.run_backfill("series", slice_size=500, time_budget_s=3600)


# ── CLI entrypoint (sync tests — main() drives its own event loop) ───────────


def test_main_rejects_invalid_content_type():
    """An unknown content type exits with a non-zero code (argparse)."""
    with pytest.raises(SystemExit) as excinfo:
        backfill_sync.main(["pizza"])
    assert excinfo.value.code != 0


def test_main_returns_zero_on_normal_stop():
    """A normal stop (exhausted/time budget) exits 0 and forwards the CLI args."""
    summary = {
        "content_type": "movie",
        "iterations": 2,
        "synced": 1000,
        "errors": 0,
        "pending": 0,
        "stuck": 0,
        "elapsed_s": 12.3,
        "stop_reason": "exhausted",
    }
    with (
        patch.object(
            backfill_sync, "run_backfill", new_callable=AsyncMock, return_value=summary
        ) as mock_run,
        patch.object(backfill_sync, "engine", new=AsyncMock()),
    ):
        code = backfill_sync.main(["movie", "--slice-size", "50", "--time-budget-minutes", "2"])

    assert code == 0
    mock_run.assert_awaited_once_with("movie", 50, 120)


def test_main_returns_one_on_unrecoverable_failure():
    """A BackfillError from the loop maps to exit code 1."""
    with (
        patch.object(
            backfill_sync,
            "run_backfill",
            new_callable=AsyncMock,
            side_effect=backfill_sync.BackfillError("no progress"),
        ),
        patch.object(backfill_sync, "engine", new=AsyncMock()),
    ):
        code = backfill_sync.main(["movie"])

    assert code == 1
