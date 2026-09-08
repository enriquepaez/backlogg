"""TMDB catalog enumeration by quality threshold (feature 86).

What this module is for
-----------------------

Until feature 86 the catalog of movies and series was *enumerated* by walking
``/movie/popular`` and ``/tv/popular`` by offset.  That method has three
defects, documented in ``docs/seeding-plan.md`` §1:

1. **Hard ceiling.** TMDB stops paginating at page 500 × 20 items = 10.000 and
   not one more.  ``SEED_TOP_N_*`` sitting at 10000 was not a product
   decision, it was the ceiling of the method.
2. **The walk is not stable.** ``/popular`` reorders itself continuously, so
   an item that was on page 30 when the cursor was on page 12 can be on page
   28 by the time the cursor gets there — and is then never visited.  The
   offset walk does not even guarantee covering those 10.000.
3. **``popularity`` is not a quality signal.**  It measures *recent interest*.
   30% of the movies ranked 20.000-40.000 have ≥50 votes, so a rank cutoff
   discards thousands of well-known titles while admitting regional theatre
   recordings.

The replacement enumerates ``/discover`` under a ``vote_count.gte`` threshold,
sliced by release year.  ``/discover`` has the *same* 500-page cap, but no
yearly slice comes close to it: measured with ``vote_count ≥ 25`` the heaviest
year is 2019 with 2.175 movies (109 pages, 22% of the allowance) and 2022 with
752 series.  There is ~4× of headroom, enough to lower the threshold later
without redesigning anything.

The 500-page guard
------------------

The headroom above is *measured*, not *guaranteed*: a lower threshold, or
TMDB's catalog simply growing, could push a year over the cap.  So the guard
is explicit rather than assumed: every window's first page reports
``total_pages``, and a window over :data:`MAX_DISCOVER_PAGES` is **split into
its twelve months** and re-enumerated month by month (a month carries ~1/12 of
the items, so a year would have to hold >60.000 items for a month to overflow
too).  If a month *still* overflows the run does not abort — that would throw
away a whole seeding pass over one bad window — it enumerates the 500 pages
TMDB is willing to serve and reports the window in
``EnumerationStats.truncated_windows`` so the truncation is visible in the
run's summary instead of silently shrinking the catalog.

The 14-day window of ``/changes`` (feature 88)
----------------------------------------------

The incremental updates of feature 88 slice time for a different reason and
against a different limit, but with the same primitive: ``/movie/changes`` and
``/tv/changes`` answer for a **date range of at most 14 days**, and — this is
the part that has consequences — TMDB only *keeps* 14 days of change history at
all.  :func:`change_windows` is the chunker (a range into consecutive closed
windows that neither overlap nor leave holes) and :func:`plan_change_windows`
is the honest planner on top of it: it clips the requested range to what TMDB
can still answer and **reports the clipped-off part as uncovered** instead of
pretending the catalog is up to date.  See its docstring.
:func:`fetch_change_ids` walks one such window's pages (100 per page here, not
20) and returns the ids it reports.

``/changes`` is subject to the 500-page cap too
-----------------------------------------------

This module used to claim the opposite — "there is no 500-page cap to guard
against because the window itself is the limit".  That premise was **false**
and the first real run against TMDB proved it: ``/movie/changes`` answers
``page=501`` with an HTTP 400, exactly like ``/discover``.

The volumes, measured against the live API on 2026-09-08:

=========================================  ============  ===============
query                                      total_pages   total_results
=========================================  ============  ===============
``/movie/changes`` 2026-08-26..2026-09-08  746           74.593
``/movie/changes`` 2026-09-07..2026-09-08  73            7.237
``/tv/changes``    2026-08-26..2026-09-08  163           16.278
=========================================  ============  ===============

That is **~73 pages per day for movies** and ~13 for series, so any movie
window longer than about six days overflows the cap — and the case that
overflows first is not an exotic one, it is the *cold start*: with no
watermark the plan asks for the whole 14-day retention window, ~1.000 pages.
The same happens on every recovery after the job has been down a few days.

So :func:`fetch_change_ids` applies the *same* guard as the ``/discover``
enumeration, reusing :data:`MAX_DISCOVER_PAGES` (TMDB's cap is one number for
every list endpoint): a window whose page 1 declares more than the cap is
**split and re-walked**, halving until each piece fits.  The floor is one
calendar day — ``/changes`` takes dates, not timestamps, so there is nothing
finer to ask for.  A single day that *still* overflows is not fatal and is not
faked either: its first 500 pages are walked and the day is reported as an
**uncovered stretch**, the same treatment the retention gap gets, so the
watermark never advances past it and the nightly ``last_synced_at`` sweep is
what refreshes those items.  At 73 pages/day that needs a 6,8× surge in TMDB's
daily change volume; it is a guard, not a forecast.

The release gate (feature 88)
-----------------------------

Feature 88 also adds an entry route the ``vote_count`` threshold structurally
cannot serve: **a release has no votes on the day it comes out**.  Those ids
arrive from the daily id export (``backlogg.scheduler.tmdb_exports``) having
proved only that they are *new to TMDB*, which is not a quality signal — TMDB
gains around a thousand ids a day, most of them regional or amateur entries
and old catalogue backfill.  :func:`release_gate_verdict` is the gate they have
to clear instead, evaluated over the detail payload because the export carries
no date at all.  It lives here, with the rest of the pure "what belongs in the
catalog" decisions, so it can be read and tested without a socket or a
database.

Separation of concerns
----------------------

The adapters (``TMDBClient.discover_movies_page`` /
``TMDBSeriesClient.discover_series_page``) do raw pagination and nothing else:
one page in, one payload out.  This module owns the slicing, the guard and the
fan-out.  It never touches the database: it hands batches of
:class:`DiscoveredTarget` to an ``on_targets`` callback so the caller decides
where they go — which is what makes a run resumable (the seeding script
persists each page as it arrives instead of accumulating 57.135 rows in
memory and losing them on a crash).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_CHANGES_WINDOW_DAYS",
    "MAX_DISCOVER_PAGES",
    "ChangeFeed",
    "ChangesPlan",
    "DateWindow",
    "DiscoveredTarget",
    "EnumerationStats",
    "ReleaseGate",
    "change_windows",
    "enumerate_windows",
    "fetch_change_ids",
    "map_discover_result",
    "month_windows",
    "plan_change_windows",
    "release_gate_verdict",
    "split_change_window",
    "year_windows",
]

# TMDB refuses to paginate past page 500 on **every** list endpoint —
# /discover (20 items per page, so 10.000 per window) and /changes (100 per
# page, so 50.000 per window) alike; page 501 answers HTTP 400.  One constant
# for both because it is one limit: the name kept its /discover origin, the
# rule never was /discover-only.
MAX_DISCOVER_PAGES = 500

# ``/movie/changes`` and ``/tv/changes`` accept a date range of at most 14 days
# per request *and* only keep 14 days of history.  One constant for both facts
# because TMDB uses one number for both; ``plan_change_windows`` takes them as
# two parameters because they have very different consequences.
MAX_CHANGES_WINDOW_DAYS = 14


@dataclass(frozen=True, slots=True)
class DateWindow:
    """A closed release-date range to enumerate as one ``/discover`` query.

    ``splittable`` marks a window that can still be broken down if it exceeds
    the page cap.  Two families use it:

    - ``/discover``: a year splits into its twelve months, a month does not
      split further (a month over the cap is truncated and reported).
    - ``/changes``: a window of two or more days splits in half, a **single
      day does not** — TMDB takes dates, not timestamps, so one day is the
      floor of what can be requested.  A saturated day is reported as an
      uncovered stretch instead.
    """

    label: str
    start: date
    end: date
    splittable: bool = False


@dataclass(frozen=True, slots=True)
class DiscoveredTarget:
    """One item the enumeration selected, before any detail is fetched.

    ``vote_count`` and ``release_year`` are kept because they are free (they
    travel in the ``/discover`` result) and they are what lets the hydration
    order the work list by notoriety, so an interrupted seeding run has the
    best of the catalog in already.
    """

    external_id: str
    vote_count: int | None
    release_year: int | None


@dataclass(slots=True)
class EnumerationStats:
    """Summary of one enumeration run — the numbers the operator needs.

    ``truncated_windows`` is the one that matters: anything above 0 means the
    catalog enumerated is *incomplete* and the threshold or the slicing needs
    revisiting.
    """

    windows: int = 0
    split_windows: int = 0
    truncated_windows: int = 0
    pages: int = 0
    targets: int = 0
    truncated_labels: list[str] = field(default_factory=list)


# ``(page, date_gte, date_lte) -> payload`` — the adapter method, already
# bound to its threshold by the caller.
PageFetcher = Callable[..., Awaitable[dict]]
TargetSink = Callable[[list[DiscoveredTarget]], Awaitable[None]]


def year_windows(start_year: int, end_year: int) -> list[DateWindow]:
    """One window per calendar year in ``[start_year, end_year]``, oldest first.

    Oldest first on purpose: the recent years are the ones that keep changing,
    so a run that has to be resumed re-does less work if the volatile end is
    the last thing it touches.
    """
    if end_year < start_year:
        raise ValueError(f"year_windows: end_year {end_year} is before start_year {start_year}")
    return [
        DateWindow(
            label=str(year),
            start=date(year, 1, 1),
            end=date(year, 12, 31),
            splittable=True,
        )
        for year in range(start_year, end_year + 1)
    ]


def month_windows(year: int) -> list[DateWindow]:
    """The twelve monthly windows of ``year`` — the fallback for a full year."""
    windows: list[DateWindow] = []
    for month in range(1, 13):
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        windows.append(
            DateWindow(
                label=f"{year}-{month:02d}",
                # ``end`` is inclusive in TMDB's ``.lte``, so step back a day
                # from the first of the next month instead of hardcoding month
                # lengths and getting February wrong every four years.
                start=start,
                end=date.fromordinal(end.toordinal() - 1),
                splittable=False,
            )
        )
    return windows


def change_windows(
    start: date,
    end: date,
    max_span_days: int = MAX_CHANGES_WINDOW_DAYS,
) -> list[DateWindow]:
    """Split ``[start, end]`` into consecutive windows of ``max_span_days`` days.

    The windows are **closed on both ends** and counted in calendar days
    inclusive, so a 14-day window is ``d .. d+13``.  Counting inclusively is
    the conservative reading of TMDB's "maximum 14 days": a window built this
    way can never be argued to be 15 days long.

    They tile the range exactly — consecutive windows are adjacent
    (``previous.end + 1 day == next.start``), so there is no overlap (an item
    changed on a boundary day is not fetched twice) and no hole (no day falls
    between two windows).  The last window is short when the range does not
    divide evenly; it is never extended past ``end``.

    ``splittable`` is True for every window of two days or more, and False for
    a one-day window.  This used to be False everywhere, on the premise that a
    change window has no page cap to escape — the premise was wrong (see the
    module docstring: 73 pages a day in movies against a 500-page cap, so the
    14-day window of a cold start declares ~1.000 pages and page 501 answers
    HTTP 400).  Splitting *does* lift the cap here, exactly as it does for a
    ``/discover`` year, and one day is the floor because the endpoint takes
    dates and not timestamps.
    """
    if end < start:
        raise ValueError(f"change_windows: end {end} is before start {start}")
    if max_span_days < 1:
        raise ValueError(f"change_windows: max_span_days must be >= 1, got {max_span_days}")

    windows: list[DateWindow] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=max_span_days - 1), end)
        windows.append(_change_window(cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _change_window(start: date, end: date) -> DateWindow:
    """One ``/changes`` window, splittable unless it is already a single day."""
    return DateWindow(
        label=f"{start.isoformat()}..{end.isoformat()}",
        start=start,
        end=end,
        splittable=end > start,
    )


def split_change_window(window: DateWindow) -> list[DateWindow]:
    """Halve ``window`` into two adjacent windows, or ``[]`` if it is one day.

    Halving rather than exploding into single days: a window over the cap is
    usually only *somewhat* over it (a 14-day movie window declares ~1.000
    pages against a cap of 500), so two 7-day halves are normally enough and
    each extra level costs only one probe request — page 1 of each half, which
    is a page the walk had to fetch anyway.  Exploding a 14-day window into 14
    daily ones would fetch 14 first pages to solve a 2× overflow.

    The two halves tile the input exactly: same start, same end, adjacent in
    the middle, so the recursion cannot invent or lose a day.  ``[]`` for a
    one-day window is the floor of the whole mechanism — ``/changes`` is
    queried with ``start_date``/``end_date``, not timestamps, so a day cannot
    be cut in two.
    """
    span = (window.end - window.start).days + 1
    if span < 2:
        return []
    midpoint = window.start + timedelta(days=span // 2 - 1)
    return [
        _change_window(window.start, midpoint),
        _change_window(midpoint + timedelta(days=1), window.end),
    ]


@dataclass(frozen=True, slots=True)
class ChangesPlan:
    """What ``/changes`` can and cannot do about the time since the last run.

    ``windows`` is what to actually request.  ``uncovered_start``/
    ``uncovered_end`` is the closed range that TMDB **will not answer for** —
    older than its retention — and is therefore *not* in ``windows``.  It is
    part of the return value rather than only a log line so the caller can act
    on it: the defined behaviour when the gap exceeds the 14-day window is to
    fall back to the full ``last_synced_at`` sweep for that stretch, and a
    caller cannot decide that from a warning it never sees.
    """

    windows: list[DateWindow]
    uncovered_start: date | None = None
    uncovered_end: date | None = None

    @property
    def has_uncovered_range(self) -> bool:
        """True when part of the requested range is unrecoverable via /changes."""
        return self.uncovered_start is not None

    @property
    def uncovered_days(self) -> int:
        """Length in calendar days of the unrecoverable stretch (0 if none)."""
        if self.uncovered_start is None or self.uncovered_end is None:
            return 0
        return (self.uncovered_end - self.uncovered_start).days + 1


def plan_change_windows(
    *,
    since: date | None,
    until: date,
    max_span_days: int = MAX_CHANGES_WINDOW_DAYS,
    retention_days: int = MAX_CHANGES_WINDOW_DAYS,
    context: str = "tmdb /changes",
) -> ChangesPlan:
    """Plan the ``/changes`` requests that cover ``[since, until]``, honestly.

    ``since`` is the **last date already covered** — literally what the caller
    persisted in ``sync_watermarks`` (``covered_through = window.end``), handed
    over unchanged so that the two sides of the watermark cannot drift apart.
    ``None`` means the mechanism has never run, so there is nothing it
    *promised* to have covered and the plan is simply the whole retention
    window.

    That day is deliberately requested **again**: it is a re-request of one
    day, not an off-by-one.  A run at 09:00 only sees the changes that day had
    produced by 09:00, and ``/changes`` is queried by whole days — so starting
    the next plan at ``since + 1`` would drop every change stamped that same
    afternoon, permanently, once the day fell out of retention.  Re-asking is
    idempotent (the lane only re-hydrates ids the catalog already holds) and
    costs one window's pagination.

    The overlap is **not** counted as a gap, though: ``uncovered_*`` starts at
    ``since + 1``, because the day of the watermark *was* covered.  Reporting
    it as lost would inflate the operational ``uncovered_days`` by one every
    single time, which is exactly the kind of number an operator stops
    believing.

    Two different limits are at play and the distinction is the whole point of
    this function:

    - ``max_span_days`` — how much a **single request** may ask for.  Handled
      by slicing, and nothing is lost.
    - ``retention_days`` — how far back TMDB **keeps** change history at all.
      Not handled by slicing, because nothing can handle it: if the last run
      was 30 days ago, days 15 to 30 are *gone* from this endpoint.

    So when ``since`` is older than the retention horizon the plan does **not**
    silently pretend to cover it.  It requests only the stretch TMDB can still
    answer, records the rest in ``uncovered_start``/``uncovered_end``, and logs
    a warning naming the days that only the full catalog sweep can refresh (the
    nightly ``last_synced_at`` rotation, kept in place by feature 88 precisely
    as the safety net for this case).

    Both limits default to the same 14 days because that is what TMDB does
    today; they are separate parameters because they are separate facts, and a
    test that narrows one without the other is exercising something real.
    """
    if retention_days < 1:
        raise ValueError(f"plan_change_windows: retention_days must be >= 1, got {retention_days}")

    # Oldest date the endpoint still answers for, counted inclusively: with
    # retention_days=14 and until=the 30th, that is the 17th.
    earliest = until - timedelta(days=retention_days - 1)

    if since is None:
        # Cold start: take the whole retention window.  Nothing is reported as
        # uncovered because nothing was ever claimed to be covered — the gap
        # before this point belongs to the seeding, not to the incremental.
        return ChangesPlan(windows=change_windows(earliest, until, max_span_days))

    if since > until:
        # Already covered past ``until`` (a re-run on the same day, or a clock
        # that moved backwards).  Nothing to request, nothing lost.
        return ChangesPlan(windows=[])

    # The watermark day is re-requested (see the docstring), but only if TMDB
    # still keeps it: past the horizon the plan starts where the endpoint can
    # still answer.
    window_start = max(since, earliest)
    # ...and the gap, if any, starts the day *after* the one already covered.
    first_uncovered = since + timedelta(days=1)

    if first_uncovered < earliest:
        uncovered_end = earliest - timedelta(days=1)
        logger.warning(
            "%s: last covered date %s is older than the %d-day retention window; "
            "%d day(s) (%s..%s) cannot be recovered through /changes and will only "
            "be refreshed by the full catalog sweep",
            context,
            since.isoformat(),
            retention_days,
            (uncovered_end - first_uncovered).days + 1,
            first_uncovered.isoformat(),
            uncovered_end.isoformat(),
        )
        return ChangesPlan(
            windows=change_windows(window_start, until, max_span_days),
            uncovered_start=first_uncovered,
            uncovered_end=uncovered_end,
        )

    return ChangesPlan(windows=change_windows(window_start, until, max_span_days))


def map_discover_result(raw: dict, date_key: str) -> DiscoveredTarget | None:
    """Map one ``/discover`` result row to a target, or None if unusable.

    ``date_key`` is ``release_date`` for movies and ``first_air_date`` for
    series.  The date is parsed explicitly (never handed to the repository as
    a string) and a malformed or missing one only costs the year, not the
    target: the item is still worth hydrating.
    """
    external_id = raw.get("id")
    if not external_id:
        return None

    release_year: int | None = None
    raw_date = raw.get(date_key) or ""
    if raw_date:
        try:
            release_year = date.fromisoformat(raw_date).year
        except ValueError:
            release_year = None

    vote_count = raw.get("vote_count")
    return DiscoveredTarget(
        external_id=str(external_id),
        vote_count=int(vote_count) if vote_count is not None else None,
        release_year=release_year,
    )


async def _emit_page(
    payload: dict,
    date_key: str,
    on_targets: TargetSink,
    stats: EnumerationStats,
) -> None:
    """Map one payload's results and hand them to the sink."""
    targets = [
        target
        for target in (map_discover_result(raw, date_key) for raw in payload.get("results", []))
        if target is not None
    ]
    stats.pages += 1
    stats.targets += len(targets)
    if targets:
        await on_targets(targets)


async def _fetch_page_guarded(
    sem: asyncio.Semaphore, fetch_page: PageFetcher, window: DateWindow, page: int
) -> dict:
    """Fetch one page under *sem*; exceptions propagate to the caller's gather."""
    async with sem:
        return await fetch_page(page=page, date_gte=window.start, date_lte=window.end)


async def _enumerate_window(
    window: DateWindow,
    *,
    fetch_page: PageFetcher,
    date_key: str,
    on_targets: TargetSink,
    sem: asyncio.Semaphore,
    stats: EnumerationStats,
) -> None:
    """Enumerate one window, splitting it by month if it exceeds the page cap."""
    first = await _fetch_page_guarded(sem, fetch_page, window, 1)
    total_pages = int(first.get("total_pages") or 1)

    if total_pages > MAX_DISCOVER_PAGES and window.splittable:
        logger.info(
            "discover %s: %d pages > %d cap — splitting into monthly windows",
            window.label,
            total_pages,
            MAX_DISCOVER_PAGES,
        )
        stats.split_windows += 1
        for month in month_windows(window.start.year):
            await _enumerate_window(
                month,
                fetch_page=fetch_page,
                date_key=date_key,
                on_targets=on_targets,
                sem=sem,
                stats=stats,
            )
        return

    stats.windows += 1
    if total_pages > MAX_DISCOVER_PAGES:
        # Nothing finer to split into. Take what TMDB serves and make the
        # shortfall loud rather than silently shipping a smaller catalog.
        logger.warning(
            "discover %s: %d pages exceed the %d-page cap and the window cannot be "
            "split further — enumerating the first %d pages only, %d items are "
            "unreachable with the current threshold",
            window.label,
            total_pages,
            MAX_DISCOVER_PAGES,
            MAX_DISCOVER_PAGES,
            (total_pages - MAX_DISCOVER_PAGES) * 20,
        )
        stats.truncated_windows += 1
        stats.truncated_labels.append(window.label)
        total_pages = MAX_DISCOVER_PAGES

    await _emit_page(first, date_key, on_targets, stats)
    if total_pages <= 1:
        return

    # Remaining pages in parallel, bounded by the shared semaphore. Results
    # are emitted in page order so the sink sees a deterministic sequence.
    payloads = await asyncio.gather(
        *(_fetch_page_guarded(sem, fetch_page, window, page) for page in range(2, total_pages + 1))
    )
    for payload in payloads:
        await _emit_page(payload, date_key, on_targets, stats)


async def enumerate_windows(
    windows: list[DateWindow],
    *,
    fetch_page: PageFetcher,
    date_key: str,
    on_targets: TargetSink,
    concurrency: int,
    stats: EnumerationStats | None = None,
) -> EnumerationStats:
    """Enumerate every window in order and stream the targets to ``on_targets``.

    Windows are processed **sequentially** while the pages *inside* a window
    are fetched in parallel (``asyncio.gather`` under a shared
    ``asyncio.Semaphore``, the same pattern as the search fan-out).  Doing it
    the other way round would put the whole enumeration in flight at once and
    blow past TMDB's rate limit; this way the in-flight request count is
    exactly ``concurrency`` regardless of how many windows there are, which is
    what keeps the run in the 30-40 req/s band ``docs/seeding-plan.md`` §4
    asks for.

    Failures are not swallowed: a page that keeps failing after the adapter's
    own retries aborts the run.  Enumeration is cheap (~3.600 requests for the
    whole catalog) and restartable, and a half-enumerated window would look
    exactly like "those items no longer meet the threshold" to every consumer
    downstream — silently shrinking the catalog is worse than stopping.
    """
    stats = stats if stats is not None else EnumerationStats()
    sem = asyncio.Semaphore(max(1, concurrency))
    for window in windows:
        await _enumerate_window(
            window,
            fetch_page=fetch_page,
            date_key=date_key,
            on_targets=on_targets,
            sem=sem,
            stats=stats,
        )
    return stats


# ── The release gate (feature 88) ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    """The quality bar a *brand new* TMDB id has to clear to enter the catalog.

    The seeded catalog is defined by ``vote_count >= 25``.  A release cannot
    satisfy that on day one — it has no votes — so the incremental would admit
    nothing if it reused the threshold, and would admit *everything TMDB
    creates* if it dropped it.  This is the third option: keep the intent of
    the threshold (only items with an audience) by admitting exactly the items
    the threshold cannot judge **yet**, and nothing else.

    ``date_key`` is ``release_date`` for movies and ``first_air_date`` for
    series, the same split ``map_discover_result`` makes.

    ``max_age_days``/``horizon_days`` bound the release date around today.  The
    date is the load-bearing check: a new *id* is not a new *item*.  TMDB gains
    roughly a thousand ids a day and the great majority of them are catalogue
    backfill — a 1978 regional documentary someone finally created a record
    for — which is precisely the material the ``vote_count`` threshold exists
    to keep out and which will enter through the promotion sweep if it ever
    earns an audience.

    ``rejected_statuses`` drops payloads whose ``status`` says the item may not
    exist at all.  It is per type because the two vocabularies do not mean the
    same thing: a movie that is ``Rumored`` or ``Canceled`` has nothing to
    watch, while a *series* marked ``Canceled`` is usually one that aired for a
    season and then was dropped — a legitimate catalog item.

    ``require_description`` demands a poster or an overview.  An entry with a
    title, a date and neither of those is a stub: nothing to render on a card
    and nothing to search.  It is the cheapest available proxy for "somebody
    other than the submitter cares", now that ``vote_count`` cannot be used.
    """

    date_key: str
    max_age_days: int
    horizon_days: int
    rejected_statuses: frozenset[str] = frozenset()
    require_description: bool = True


def release_gate_verdict(detail: dict, *, gate: ReleaseGate, today: date) -> str | None:
    """``None`` if ``detail`` clears ``gate``, otherwise the reason it did not.

    A string rather than a bool because the reasons are the only way to tell a
    gate that is doing its job from one that is silently rejecting everything:
    the job counts them by reason and logs the tally.

    The date is parsed here with ``date.fromisoformat`` (never handed to the
    repository as a string, ``docs/conventions.md``) and a *missing or
    unparseable* one is a rejection, not a pass.  That asymmetry with
    ``map_discover_result`` — which tolerates a bad date because the item had
    already qualified on votes — is the whole point: here the date is the
    qualification.
    """
    if not (detail.get("title") or detail.get("name")):
        return "no_title"
    if detail.get("adult"):
        return "adult"
    if detail.get("video"):
        return "video"

    status = detail.get("status")
    if status and status in gate.rejected_statuses:
        return f"status:{status}"

    raw_date = detail.get(gate.date_key) or ""
    if not raw_date:
        return "no_release_date"
    try:
        released = date.fromisoformat(raw_date)
    except ValueError:
        return "unparseable_release_date"

    if released < today - timedelta(days=gate.max_age_days):
        return "too_old"
    if released > today + timedelta(days=gate.horizon_days):
        return "too_far_ahead"

    if gate.require_description and not (detail.get("poster_path") or detail.get("overview")):
        return "no_poster_or_overview"

    return None


# ── Walking ``/changes`` (feature 88) ────────────────────────────────────────


async def _fetch_change_page_guarded(
    sem: asyncio.Semaphore, fetch_page: PageFetcher, window: DateWindow, page: int
) -> dict:
    """Fetch one ``/changes`` page under *sem*; exceptions propagate."""
    async with sem:
        return await fetch_page(page=page, start_date=window.start, end_date=window.end)


def _change_ids(payload: dict) -> list[str]:
    """The ids of one ``/changes`` page, in payload order."""
    return [str(raw["id"]) for raw in payload.get("results", []) if raw.get("id") is not None]


@dataclass(frozen=True, slots=True)
class ChangeFeed:
    """What one ``/changes`` window produced — ids *and* how much was covered.

    ``ids`` is the de-duplicated id list, first seen first.  The rest exists
    because a window is not always covered whole: ``/changes`` has the same
    500-page cap as ``/discover`` (~73 pages per day in movies, so a 14-day
    cold start declares ~1.000), and a day that overflows it on its own cannot
    be sliced any thinner.

    ``covered_through`` is the load-bearing field: the last day of the window
    for which the walk saw **every** page, or ``None`` when not even the first
    day was complete.  The caller advances the watermark to exactly this and
    to nothing beyond, which is what keeps "the watermark moved" meaning "that
    range was covered" — the same contract the retention gap honours by
    reporting ``uncovered_*`` instead of pretending.

    ``truncated_labels`` names the days whose first 500 pages were taken and
    whose remainder was left behind, so the shortfall is a number in the run
    summary and not an inference from the logs.
    """

    ids: list[str]
    windows: int = 0
    pages: int = 0
    covered_through: date | None = None
    truncated_labels: list[str] = field(default_factory=list)

    @property
    def truncated_windows(self) -> int:
        """How many single-day windows hit the page cap (0 in a healthy run)."""
        return len(self.truncated_labels)


@dataclass(slots=True)
class _ChangeWalk:
    """Mutable accumulator threaded through the recursive window walk."""

    ids: dict[str, None] = field(default_factory=dict)
    windows: int = 0
    pages: int = 0
    truncated_labels: list[str] = field(default_factory=list)
    first_truncated_day: date | None = None


async def _walk_change_window(
    window: DateWindow,
    *,
    fetch_page: PageFetcher,
    sem: asyncio.Semaphore,
    walk: _ChangeWalk,
) -> None:
    """Walk one window's pages, halving it first if it exceeds the page cap.

    Structurally the same guard as :func:`_enumerate_window`: page 1 is
    fetched first because only it reports ``total_pages``; over the cap and
    still splittable means re-walk the halves; over the cap with nothing left
    to split means take the pages TMDB serves and record the day.

    The parent's page 1 is *discarded* when the window splits — every id on it
    belongs to a day one of the halves covers, so nothing is lost, and
    dropping it keeps the id order equal to the chronological walk order.
    """
    first = await _fetch_change_page_guarded(sem, fetch_page, window, 1)
    walk.pages += 1
    total_pages = int(first.get("total_pages") or 1)

    if total_pages > MAX_DISCOVER_PAGES and window.splittable:
        halves = split_change_window(window)
        logger.info(
            "changes %s: %d pages > %d cap — splitting into %s",
            window.label,
            total_pages,
            MAX_DISCOVER_PAGES,
            " and ".join(half.label for half in halves),
        )
        for half in halves:
            await _walk_change_window(half, fetch_page=fetch_page, sem=sem, walk=walk)
        return

    walk.windows += 1
    if total_pages > MAX_DISCOVER_PAGES:
        # A single day over the cap: nothing finer to ask TMDB for.  Take the
        # 500 pages it serves — a partial refresh beats none — but do not let
        # the day count as covered.
        logger.warning(
            "changes %s: %d pages exceed the %d-page cap and a single day cannot be "
            "split further — walking the first %d pages only; ~%d changed id(s) of "
            "that day are unreachable through /changes and stay for the nightly "
            "last_synced_at sweep",
            window.label,
            total_pages,
            MAX_DISCOVER_PAGES,
            MAX_DISCOVER_PAGES,
            (total_pages - MAX_DISCOVER_PAGES) * 100,
        )
        walk.truncated_labels.append(window.label)
        if walk.first_truncated_day is None:
            walk.first_truncated_day = window.start
        total_pages = MAX_DISCOVER_PAGES

    walk.ids.update(dict.fromkeys(_change_ids(first)))
    if total_pages <= 1:
        return

    payloads = await asyncio.gather(
        *(
            _fetch_change_page_guarded(sem, fetch_page, window, page)
            for page in range(2, total_pages + 1)
        )
    )
    for payload in payloads:
        walk.pages += 1
        walk.ids.update(dict.fromkeys(_change_ids(payload)))


async def fetch_change_ids(
    window: DateWindow,
    *,
    fetch_page: PageFetcher,
    concurrency: int,
) -> ChangeFeed:
    """Every distinct id ``/changes`` reports for ``window``, first seen first.

    Same fetch shape as the ``/discover`` enumeration — page 1 first because
    only it can report ``total_pages``, then the rest in parallel under a
    semaphore — and, contrary to what this docstring claimed until the first
    production run, **the same 500-page cap**.  ``page=501`` answers HTTP 400
    here too; measured on 2026-09-08 a 13-day movie window declares 746 pages
    (~73 a day, ~13 a day for series), so the window span alone does not keep
    the walk inside the cap: the 14-day window of a cold start is ~1.000
    pages.

    So a window over the cap is halved and re-walked (:func:`split_change_window`)
    until each piece fits, down to a floor of one calendar day.  A day that
    overflows on its own is walked for its first 500 pages and reported in
    ``ChangeFeed.truncated_labels``; ``covered_through`` then stops at the day
    *before* it, so the caller's watermark cannot move past a stretch that was
    not covered.  A saturated day is never fatal — aborting would throw away
    the whole run over one busy day — and never silent.

    Pages hold 100 ids instead of 20.  That page size is TMDB's and is not
    sent as a parameter, so there is no constant for it here: it is walked
    through ``total_pages``.  It is worth knowing all the same, because it is
    what sets the arithmetic above (500 pages = 50.000 ids per window).

    De-duplicated: an item changed twice in the window is reported twice and
    re-hydrating it twice would be pure waste.  Order is preserved so the run
    is deterministic.

    Failures propagate.  The caller advances the watermark **per window**, so a
    window that raises simply leaves the watermark at the end of the last one
    that completed and the range is re-requested next run — which is the only
    way "the watermark moved" can keep meaning "the range was covered".
    """
    sem = asyncio.Semaphore(max(1, concurrency))
    walk = _ChangeWalk()
    await _walk_change_window(window, fetch_page=fetch_page, sem=sem, walk=walk)

    if walk.first_truncated_day is None:
        covered_through: date | None = window.end
    elif walk.first_truncated_day > window.start:
        # Everything before the first saturated day was walked whole.
        covered_through = walk.first_truncated_day - timedelta(days=1)
    else:
        # The window's very first day saturated: nothing in it is covered.
        covered_through = None

    return ChangeFeed(
        ids=list(walk.ids),
        windows=walk.windows,
        pages=walk.pages,
        covered_through=covered_through,
        truncated_labels=walk.truncated_labels,
    )
