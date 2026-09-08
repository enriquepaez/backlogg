"""Tests for feature 88 (phase A) — the state core of the incremental updates.

Covers:
- ``change_windows``: a range longer than TMDB's 14 days is sliced into
  consecutive windows that neither overlap nor leave a hole;
- ``plan_change_windows``: ``since`` is the **last day already covered** (the
  watermark, verbatim), that day is re-requested on purpose and never counted
  as a gap, and when the stretch after it is older than what ``/changes`` keeps
  the unrecoverable part is reported (return value *and* warning) instead of
  being silently swallowed;
- the ``sync_watermarks`` repository against the real test database: first
  write creates, second updates the same row, and two mechanisms never clobber
  each other.

The TMDB/IGDB/Open Library mechanisms that *write* these watermarks are phases
B and C of the feature; nothing here talks to an external API.
"""

import logging
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from backlogg.scheduler.discovery import (
    MAX_CHANGES_WINDOW_DAYS,
    change_windows,
    plan_change_windows,
    split_change_window,
)
from backlogg.scheduler.repository import get_sync_watermark, set_sync_watermark
from backlogg.shared.models import SyncWatermark

DISCOVERY_LOGGER = "backlogg.scheduler.discovery"


@contextmanager
def _captured_warnings():
    """Capture ``discovery``'s own warnings, robust to the rest of the suite.

    A handler on the module logger instead of pytest's ``caplog`` fixture:
    ``configure_logging`` strips the root handlers (the captured one among
    them) whenever another test builds the app, which would silently empty
    these assertions.  Same reasoning and same shape as
    ``tests/shared/test_link_skip_observability.py``.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.NOTSET)
    module_logger = logging.getLogger(DISCOVERY_LOGGER)
    module_logger.addHandler(handler)
    previous_level = module_logger.level
    module_logger.setLevel(logging.WARNING)
    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    previous_disabled_flag = module_logger.disabled
    module_logger.disabled = False
    try:
        yield records
    finally:
        module_logger.disabled = previous_disabled_flag
        logging.disable(previous_disable)
        module_logger.setLevel(previous_level)
        module_logger.removeHandler(handler)


def _assert_tiles(windows, start: date, end: date, max_span_days: int) -> None:
    """The windows tile [start, end] exactly: no overlap, no hole, no overflow."""
    assert windows, "expected at least one window"
    assert windows[0].start == start
    assert windows[-1].end == end
    for window in windows:
        assert window.start <= window.end
        # Inclusive day count, the conservative reading of "maximum 14 days".
        assert (window.end - window.start).days + 1 <= max_span_days
    for previous, following in zip(windows, windows[1:], strict=False):
        # Adjacent: no day is requested twice and no day falls between two
        # windows.  Both failure modes are silent in production — an overlap
        # only wastes requests, a hole loses changes forever.
        assert following.start == previous.end + timedelta(days=1)


# ── change_windows: slicing a range longer than 14 days ──────────────────────


def test_change_windows_slices_a_range_longer_than_the_tmdb_window():
    """A 40-day range becomes 14 + 14 + 12 days, in order."""
    start = date(2026, 8, 1)
    end = date(2026, 9, 9)  # 40 days inclusive

    windows = change_windows(start, end)

    assert [(w.start, w.end) for w in windows] == [
        (date(2026, 8, 1), date(2026, 8, 14)),
        (date(2026, 8, 15), date(2026, 8, 28)),
        (date(2026, 8, 29), date(2026, 9, 9)),
    ]
    _assert_tiles(windows, start, end, MAX_CHANGES_WINDOW_DAYS)


def test_change_windows_tiles_without_overlap_or_hole_over_a_long_range():
    """Every day of a 100-day range is covered exactly once."""
    start = date(2026, 1, 1)
    end = start + timedelta(days=99)

    windows = change_windows(start, end)

    _assert_tiles(windows, start, end, MAX_CHANGES_WINDOW_DAYS)
    covered = [
        window.start + timedelta(days=offset)
        for window in windows
        for offset in range((window.end - window.start).days + 1)
    ]
    assert covered == [start + timedelta(days=offset) for offset in range(100)]
    assert len(covered) == len(set(covered))


def test_change_windows_exact_multiple_produces_equal_windows():
    """28 days at 14 per window is two full windows and no remainder."""
    start = date(2026, 3, 1)
    windows = change_windows(start, start + timedelta(days=27))

    assert len(windows) == 2
    assert all((w.end - w.start).days + 1 == 14 for w in windows)


def test_change_windows_single_day_is_one_window():
    """A one-day range is a legitimate window, not an empty plan."""
    day = date(2026, 5, 20)
    windows = change_windows(day, day)

    assert len(windows) == 1
    assert windows[0].start == windows[0].end == day
    assert windows[0].label == "2026-05-20..2026-05-20"


def test_change_windows_of_more_than_one_day_are_splittable():
    """Splitting *does* lift a cap here: /changes tops out at 500 pages too.

    This used to assert the opposite.  The premise was wrong — measured
    2026-09-08, a 13-day movie window declares 746 pages — and a window that
    cannot be split is a window that dies on ``page=501`` with an HTTP 400.
    """
    windows = change_windows(date(2026, 1, 1), date(2026, 2, 28))

    assert all(window.splittable is True for window in windows)


def test_a_one_day_change_window_is_not_splittable():
    """One day is the floor: /changes takes dates, not timestamps."""
    day = date(2026, 5, 20)
    windows = change_windows(day, day)

    assert windows[0].splittable is False
    assert split_change_window(windows[0]) == []


def test_split_change_window_halves_without_overlap_or_hole():
    """The two halves tile the input exactly, so recursion cannot lose a day."""
    window = change_windows(date(2026, 5, 1), date(2026, 5, 14))[0]

    halves = split_change_window(window)

    assert [(h.start, h.end) for h in halves] == [
        (date(2026, 5, 1), date(2026, 5, 7)),
        (date(2026, 5, 8), date(2026, 5, 14)),
    ]
    _assert_tiles(halves, window.start, window.end, MAX_CHANGES_WINDOW_DAYS)


def test_split_change_window_of_two_days_reaches_the_one_day_floor():
    """The recursion terminates: two days split into two unsplittable days."""
    window = change_windows(date(2026, 5, 1), date(2026, 5, 2))[0]

    halves = split_change_window(window)

    assert [(h.start, h.end) for h in halves] == [
        (date(2026, 5, 1), date(2026, 5, 1)),
        (date(2026, 5, 2), date(2026, 5, 2)),
    ]
    assert all(half.splittable is False for half in halves)
    assert all(split_change_window(half) == [] for half in halves)


def test_split_change_window_of_an_odd_span_still_tiles():
    """An odd span cannot halve evenly; it must still cover every day once."""
    window = change_windows(date(2026, 5, 1), date(2026, 5, 5))[0]

    halves = split_change_window(window)

    assert [(h.start, h.end) for h in halves] == [
        (date(2026, 5, 1), date(2026, 5, 2)),
        (date(2026, 5, 3), date(2026, 5, 5)),
    ]
    _assert_tiles(halves, window.start, window.end, MAX_CHANGES_WINDOW_DAYS)


def test_change_windows_rejects_an_inverted_range():
    with pytest.raises(ValueError, match="before start"):
        change_windows(date(2026, 5, 2), date(2026, 5, 1))


def test_change_windows_rejects_a_non_positive_span():
    with pytest.raises(ValueError, match="max_span_days"):
        change_windows(date(2026, 5, 1), date(2026, 5, 10), max_span_days=0)


# ── plan_change_windows: the gap that /changes cannot recover ────────────────


def test_plan_reports_the_stretch_older_than_the_retention_window():
    """A 30-day gap: only the last 14 days are requestable, the rest is lost."""
    until = date(2026, 9, 30)
    since = date(2026, 9, 1)  # the last day already covered

    with _captured_warnings() as records:
        plan = plan_change_windows(since=since, until=until)

    # Requested: only what TMDB still keeps.
    assert [(w.start, w.end) for w in plan.windows] == [(date(2026, 9, 17), until)]
    # Reported: the rest, explicitly, as part of the return value. It starts on
    # the 2nd, not the 1st: the 1st is the watermark, and the watermark records
    # a day that *was* covered.
    assert plan.has_uncovered_range is True
    assert plan.uncovered_start == date(2026, 9, 2)
    assert plan.uncovered_end == date(2026, 9, 16)
    assert plan.uncovered_days == 15
    # And nothing is double-counted: the uncovered stretch ends the day before
    # the first requested window starts.
    assert plan.uncovered_end + timedelta(days=1) == plan.windows[0].start
    # 15 uncovered + 14 requested == the 29 days that follow the covered one.
    assert (
        plan.uncovered_days + sum((w.end - w.start).days + 1 for w in plan.windows)
        == (until - since).days
    )

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "cannot be recovered through /changes" in message
    assert "2026-09-02..2026-09-16" in message


def test_plan_within_the_retention_window_covers_everything():
    """A 5-day gap fits: one window, nothing uncovered, no warning."""
    until = date(2026, 9, 30)
    since = date(2026, 9, 26)

    with _captured_warnings() as records:
        plan = plan_change_windows(since=since, until=until)

    assert [(w.start, w.end) for w in plan.windows] == [(since, until)]
    assert plan.has_uncovered_range is False
    assert plan.uncovered_days == 0
    assert [r for r in records if r.levelno == logging.WARNING] == []


def test_plan_at_exactly_the_retention_edge_is_still_fully_covered():
    """14 days inclusive is the last gap /changes can still close."""
    until = date(2026, 9, 30)
    since = until - timedelta(days=MAX_CHANGES_WINDOW_DAYS - 1)

    with _captured_warnings() as records:
        plan = plan_change_windows(since=since, until=until)

    assert plan.has_uncovered_range is False
    assert [(w.start, w.end) for w in plan.windows] == [(since, until)]
    assert [r for r in records if r.levelno == logging.WARNING] == []


def test_plan_one_day_past_the_edge_reports_a_single_uncovered_day():
    """The first day that falls out of retention is reported, not rounded away."""
    until = date(2026, 9, 30)
    # The watermark day itself is out of retention *and* so is the day after
    # it, which is the first day nobody covered.
    since = until - timedelta(days=MAX_CHANGES_WINDOW_DAYS + 1)

    plan = plan_change_windows(since=since, until=until)

    assert plan.uncovered_days == 1
    assert plan.uncovered_start == plan.uncovered_end == since + timedelta(days=1)


def test_plan_never_counts_the_watermark_day_itself_as_uncovered():
    """``since`` is the last day *covered*, so it is never part of the gap.

    This is the boundary that fixes the off-by-one: a watermark exactly one
    day older than the retention horizon leaves **nothing** uncovered — every
    day after it is still requestable — even though that day can no longer be
    re-requested itself. Reporting 1 here would add a phantom day to
    ``uncovered_days`` on every single run whose watermark sits at the edge.
    """
    until = date(2026, 9, 30)
    since = until - timedelta(days=MAX_CHANGES_WINDOW_DAYS)  # 2026-09-16

    with _captured_warnings() as records:
        plan = plan_change_windows(since=since, until=until)

    assert plan.has_uncovered_range is False
    assert plan.uncovered_days == 0
    # And the plan starts where TMDB can still answer, not at the unreachable
    # watermark day.
    assert [(w.start, w.end) for w in plan.windows] == [(since + timedelta(days=1), until)]
    assert [r for r in records if r.levelno == logging.WARNING] == []


def test_plan_re_requests_the_day_the_watermark_recorded():
    """The one-day overlap is deliberate, so it is pinned by a test.

    A run at 09:00 covers only part of that calendar day, and ``/changes`` is
    queried by whole days: starting the next plan at ``since + 1`` would drop
    that afternoon's changes for good. The plan therefore starts *on* the
    watermark day whenever retention still allows it.
    """
    until = date(2026, 9, 30)
    since = date(2026, 9, 28)

    plan = plan_change_windows(since=since, until=until)

    assert plan.windows[0].start == since
    assert plan.has_uncovered_range is False


def test_plan_cold_start_takes_the_whole_retention_window():
    """No watermark yet: request what TMDB keeps, and claim nothing was lost."""
    until = date(2026, 9, 30)

    with _captured_warnings() as records:
        plan = plan_change_windows(since=None, until=until)

    assert [(w.start, w.end) for w in plan.windows] == [(date(2026, 9, 17), until)]
    # The stretch before a first run belongs to the seeding, not to a gap the
    # incremental failed to cover — so no warning and no uncovered range.
    assert plan.has_uncovered_range is False
    assert [r for r in records if r.levelno == logging.WARNING] == []


def test_plan_already_covered_requests_nothing():
    """A second run on the same day asks for nothing and loses nothing."""
    plan = plan_change_windows(since=date(2026, 10, 1), until=date(2026, 9, 30))

    assert plan.windows == []
    assert plan.has_uncovered_range is False


def test_plan_slices_when_the_request_cap_is_narrower_than_the_retention():
    """The two limits are separate facts: a wider retention still gets sliced."""
    until = date(2026, 9, 30)
    since = date(2026, 9, 1)

    plan = plan_change_windows(since=since, until=until, max_span_days=7, retention_days=30)

    assert plan.has_uncovered_range is False
    _assert_tiles(plan.windows, since, until, 7)
    assert len(plan.windows) == 5  # 7 + 7 + 7 + 7 + 2


# ── sync_watermarks repository (real test DB) ────────────────────────────────


async def _count_watermarks(db) -> int:
    result = await db.execute(select(func.count()).select_from(SyncWatermark))
    return result.scalar_one()


async def test_get_sync_watermark_returns_none_when_never_run(db):
    """The absence of the row is the cold start, and it is not an error."""
    assert await get_sync_watermark(db, "TMDB", "CHANGES", "MOVIE") is None


async def test_set_sync_watermark_creates_then_reads_back(db):
    """First write creates the row with its cut-off and its run timestamp."""
    ran_at = datetime(2026, 9, 8, 2, 30, tzinfo=UTC)

    await set_sync_watermark(
        db,
        "TMDB",
        "CHANGES",
        "MOVIE",
        cursor_value="2026-09-08T02:00:00+00:00",
        last_run_at=ran_at,
    )

    watermark = await get_sync_watermark(db, "TMDB", "CHANGES", "MOVIE")
    assert watermark is not None
    assert watermark.source == "TMDB"
    assert watermark.kind == "CHANGES"
    assert watermark.item_type == "MOVIE"
    assert watermark.cursor_value == "2026-09-08T02:00:00+00:00"
    assert watermark.last_run_at == ran_at
    assert await _count_watermarks(db) == 1


async def test_set_sync_watermark_updates_the_same_row(db):
    """Second write advances the cut-off in place — no duplicate row."""
    first = datetime(2026, 9, 8, 2, 0, tzinfo=UTC)
    second = datetime(2026, 9, 9, 2, 0, tzinfo=UTC)

    await set_sync_watermark(
        db, "TMDB", "CHANGES", "MOVIE", cursor_value="2026-09-08", last_run_at=first
    )
    await set_sync_watermark(
        db, "TMDB", "CHANGES", "MOVIE", cursor_value="2026-09-09", last_run_at=second
    )

    watermark = await get_sync_watermark(db, "TMDB", "CHANGES", "MOVIE")
    assert watermark is not None
    assert watermark.cursor_value == "2026-09-09"
    assert watermark.last_run_at == second
    assert await _count_watermarks(db) == 1


async def test_watermarks_of_different_sources_do_not_collide(db):
    """TMDB, IGDB and Open Library each keep their own position."""
    await set_sync_watermark(db, "TMDB", "CHANGES", "MOVIE", cursor_value="2026-09-08")
    await set_sync_watermark(db, "IGDB", "UPDATED_AT", "GAME", cursor_value="1757289600")
    await set_sync_watermark(db, "OPEN_LIBRARY", "MONTHLY_DUMP", "BOOK", cursor_value="2026-08")

    tmdb = await get_sync_watermark(db, "TMDB", "CHANGES", "MOVIE")
    igdb = await get_sync_watermark(db, "IGDB", "UPDATED_AT", "GAME")
    books = await get_sync_watermark(db, "OPEN_LIBRARY", "MONTHLY_DUMP", "BOOK")

    assert tmdb is not None and tmdb.cursor_value == "2026-09-08"
    assert igdb is not None and igdb.cursor_value == "1757289600"
    assert books is not None and books.cursor_value == "2026-08"
    assert await _count_watermarks(db) == 3


async def test_watermarks_of_two_mechanisms_of_the_same_source_are_independent(db):
    """/changes can be days behind the daily export without dragging it back."""
    await set_sync_watermark(db, "TMDB", "CHANGES", "MOVIE", cursor_value="2026-09-01")
    await set_sync_watermark(db, "TMDB", "DAILY_ID_EXPORT", "MOVIE", cursor_value="2026-09-08")

    changes = await get_sync_watermark(db, "TMDB", "CHANGES", "MOVIE")
    export = await get_sync_watermark(db, "TMDB", "DAILY_ID_EXPORT", "MOVIE")

    assert changes is not None and changes.cursor_value == "2026-09-01"
    assert export is not None and export.cursor_value == "2026-09-08"
    assert await _count_watermarks(db) == 2


async def test_watermarks_of_movies_and_series_are_independent(db):
    """Same source, same mechanism, two passes: two rows."""
    await set_sync_watermark(db, "TMDB", "CHANGES", "MOVIE", cursor_value="2026-09-08")
    await set_sync_watermark(db, "TMDB", "CHANGES", "SERIES", cursor_value="2026-09-05")

    movies = await get_sync_watermark(db, "TMDB", "CHANGES", "MOVIE")
    series = await get_sync_watermark(db, "TMDB", "CHANGES", "SERIES")

    assert movies is not None and movies.cursor_value == "2026-09-08"
    assert series is not None and series.cursor_value == "2026-09-05"
    assert await _count_watermarks(db) == 2


async def test_set_sync_watermark_accepts_a_null_cursor(db):
    """ "Ran but found no cut-off" is a real state, distinct from "never ran"."""
    await set_sync_watermark(db, "IGDB", "CREATED_AT", "GAME", cursor_value=None)

    watermark = await get_sync_watermark(db, "IGDB", "CREATED_AT", "GAME")
    assert watermark is not None
    assert watermark.cursor_value is None
    assert watermark.last_run_at is not None


async def test_set_sync_watermark_defaults_last_run_to_the_database_clock(db):
    """A mechanism that just finished does not have to supply a timestamp."""
    before = datetime.now(UTC)

    await set_sync_watermark(db, "TMDB", "CHANGES", "SERIES", cursor_value="2026-09-08")

    watermark = await get_sync_watermark(db, "TMDB", "CHANGES", "SERIES")
    assert watermark is not None
    assert watermark.last_run_at >= before - timedelta(minutes=5)


async def test_set_sync_watermark_rejects_a_naive_timestamp(db):
    """timestamptz plus a naive value is how a watermark ends up hours off."""
    with pytest.raises(ValueError, match="timezone-aware"):
        await set_sync_watermark(
            db,
            "TMDB",
            "CHANGES",
            "MOVIE",
            cursor_value="2026-09-08",
            last_run_at=datetime(2026, 9, 8, 2, 0),
        )
