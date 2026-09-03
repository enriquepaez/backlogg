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
from datetime import date

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_DISCOVER_PAGES",
    "DateWindow",
    "DiscoveredTarget",
    "EnumerationStats",
    "enumerate_windows",
    "map_discover_result",
    "month_windows",
    "year_windows",
]

# TMDB refuses to paginate past page 500 on every list endpoint, /discover
# included. 20 items per page, so a single window can expose at most 10.000.
MAX_DISCOVER_PAGES = 500


@dataclass(frozen=True, slots=True)
class DateWindow:
    """A closed release-date range to enumerate as one ``/discover`` query.

    ``splittable`` marks a window that can still be broken down if it exceeds
    the page cap: years can (into months), months cannot.  TMDB offers no
    finer date granularity worth using — a daily slice would multiply the
    request count by 30 to solve a case that cannot occur.
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
