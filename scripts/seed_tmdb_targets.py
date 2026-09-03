"""Enumerate the TMDB catalog target list into ``seed_targets`` (feature 86).

This is the *enumeration* half of the seeding split described in
``docs/seeding-plan.md`` §3.  It answers one question — "which TMDB items
clear the quality threshold" — and writes the answer to ``seed_targets``.  It
fetches **no item detail and writes no catalog row**; hydration is a separate
pass (``scripts/backfill_sync.py movie`` / the nightly
``POST /admin/sync/{type}``), driven by the difference between this list and
``external_ids``.

Why it is a script and not an endpoint: a full enumeration is ~2.900 requests
for movies and ~600 for series, several minutes of wall clock, and Render caps
a request at ~15 min.  It belongs on GitHub Actions against Neon, exactly like
``scripts/backfill_sync.py`` — so no HTTP surface is added and ``bruno/`` does
not change.

Method::

    GET /discover/movie?include_adult=false&include_video=false
        &vote_count.gte=25
        &primary_release_date.gte=YYYY-01-01&primary_release_date.lte=YYYY-12-31

one window per release year, ``first_air_date`` instead of
``primary_release_date`` for series.  ``/discover`` caps pagination at 500
pages like every TMDB list endpoint, so the orchestrator checks
``total_pages`` on each window's first page and **splits a year into its twelve
months** if it would overflow (``backlogg/scheduler/discovery.py``).

Re-running is safe and cheap: targets are upserted on
``(item_type, source, external_id)``, keeping their attempt counters, so a
re-enumeration only adds newly-qualifying items and refreshes the observed
``vote_count``/``release_year``.  Each page is persisted as it arrives, so an
interrupted run keeps everything it had already enumerated.

Usage::

    uv run python scripts/seed_tmdb_targets.py movie
    uv run python scripts/seed_tmdb_targets.py series --min-votes 50
    uv run python scripts/seed_tmdb_targets.py movie --start-year 2000 --end-year 2026

Environment overrides for the defaults: ``TMDB_SEED_MIN_VOTES_MOVIES``,
``TMDB_SEED_MIN_VOTES_SERIES``, ``TMDB_SEED_START_YEAR``,
``TMDB_SEED_END_YEAR`` and ``TMDB_SEED_CONCURRENCY``.

Exit codes: 0 on success, 1 on an unrecoverable enumeration failure, 2 if any
window had to be truncated at 500 pages — the catalog enumerated is then
incomplete and the threshold or the slicing needs revisiting, which must not
be reported as a green run.
"""

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

# The project is not an installed package: make `backlogg` importable when the
# script runs standalone (uv run python scripts/seed_tmdb_targets.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backlogg.core.config import settings  # noqa: E402
from backlogg.core.database import async_session_factory, engine  # noqa: E402
from backlogg.movies.adapters.tmdb import TMDBClient  # noqa: E402
from backlogg.scheduler.discovery import (  # noqa: E402
    DiscoveredTarget,
    EnumerationStats,
    enumerate_windows,
    year_windows,
)
from backlogg.scheduler.repository import (  # noqa: E402
    SeedTargetRow,
    count_seed_target_progress,
    count_seed_targets,
    upsert_seed_targets,
)
from backlogg.series.adapters.tmdb import TMDBSeriesClient  # noqa: E402

logger = logging.getLogger("seed_tmdb_targets")

_SOURCE = "TMDB"

# Per content type: the polymorphic item_type, the date field of the discover
# result, the setting holding its vote threshold and the adapter page fetcher.
_CONTENT_TYPES = {
    "movie": {
        "item_type": "MOVIE",
        "date_key": "release_date",
        "min_votes_setting": "TMDB_SEED_MIN_VOTES_MOVIES",
    },
    "series": {
        "item_type": "SERIES",
        "date_key": "first_air_date",
        "min_votes_setting": "TMDB_SEED_MIN_VOTES_SERIES",
    },
}


def _page_fetcher(content_type: str, min_votes: int):
    """Bind the right adapter method to the run's threshold."""
    if content_type == "movie":
        return partial(TMDBClient().discover_movies_page, min_votes=min_votes)
    return partial(TMDBSeriesClient().discover_series_page, min_votes=min_votes)


def _resolve_end_year(end_year: int | None) -> int:
    """Default the end of the range to next year (TMDB carries dated future releases)."""
    if end_year is not None:
        return end_year
    if settings.TMDB_SEED_END_YEAR is not None:
        return settings.TMDB_SEED_END_YEAR
    return datetime.now(UTC).year + 1


async def _persist(item_type: str, targets: list[DiscoveredTarget]) -> None:
    """Sink for the enumerator: write one page's targets and commit.

    Committing per page is what makes the run resumable — an enumeration that
    dies on window 90 of 150 keeps the 89 windows it already wrote.
    """
    rows = [
        SeedTargetRow(
            item_type=item_type,
            source=_SOURCE,
            external_id=target.external_id,
            vote_count=target.vote_count,
            release_year=target.release_year,
        )
        for target in targets
    ]
    async with async_session_factory() as session:
        await upsert_seed_targets(session, rows)
        await session.commit()


async def run_enumeration(
    content_type: str, min_votes: int, start_year: int, end_year: int, concurrency: int
) -> dict:
    """Enumerate one content type and return a summary dict."""
    config = _CONTENT_TYPES[content_type]
    item_type = str(config["item_type"])

    logger.info(
        "seed %s: enumerating /discover with vote_count>=%d over %d-%d (concurrency=%d, source=%s)",
        content_type,
        min_votes,
        start_year,
        end_year,
        concurrency,
        _SOURCE,
    )

    stats: EnumerationStats = await enumerate_windows(
        year_windows(start_year, end_year),
        fetch_page=_page_fetcher(content_type, min_votes),
        date_key=str(config["date_key"]),
        on_targets=partial(_persist, item_type),
        concurrency=concurrency,
    )

    async with async_session_factory() as session:
        total = await count_seed_targets(session, item_type, _SOURCE)
        progress = await count_seed_target_progress(
            session, item_type, _SOURCE, max(1, settings.TMDB_SEED_MAX_ATTEMPTS)
        )

    return {
        "content_type": content_type,
        "min_votes": min_votes,
        "start_year": start_year,
        "end_year": end_year,
        "windows": stats.windows,
        "split_windows": stats.split_windows,
        "truncated_windows": stats.truncated_windows,
        "truncated_labels": stats.truncated_labels,
        "pages": stats.pages,
        "enumerated": stats.targets,
        "targets_total": total,
        "targets_pending": progress.pending,
        "targets_stuck": progress.stuck,
    }


async def _amain(
    content_type: str, min_votes: int, start_year: int, end_year: int, concurrency: int
) -> dict:
    try:
        return await run_enumeration(content_type, min_votes, start_year, end_year, concurrency)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("content_type", choices=sorted(_CONTENT_TYPES))
    parser.add_argument(
        "--min-votes",
        type=int,
        default=None,
        help="vote_count.gte threshold (default: TMDB_SEED_MIN_VOTES_MOVIES / _SERIES)",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=settings.TMDB_SEED_START_YEAR,
        help=f"first release year to enumerate (default {settings.TMDB_SEED_START_YEAR}, "
        "env TMDB_SEED_START_YEAR)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="last release year to enumerate (default: TMDB_SEED_END_YEAR, or next year)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=settings.TMDB_SEED_CONCURRENCY,
        help=f"in-flight /discover requests (default {settings.TMDB_SEED_CONCURRENCY}, "
        "env TMDB_SEED_CONCURRENCY)",
    )
    args = parser.parse_args(argv)

    min_votes = args.min_votes
    if min_votes is None:
        min_votes = getattr(settings, str(_CONTENT_TYPES[args.content_type]["min_votes_setting"]))
    end_year = _resolve_end_year(args.end_year)
    if end_year < args.start_year:
        parser.error(f"--end-year {end_year} is before --start-year {args.start_year}")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        summary = asyncio.run(
            _amain(args.content_type, min_votes, args.start_year, end_year, args.concurrency)
        )
    except Exception:
        logger.exception("seed %s: enumeration failed unrecoverably", args.content_type)
        return 1

    logger.info(
        "seed %s: finished — %d windows (%d split by month), %d pages, %d results seen, "
        "%d targets in the list, %d still missing from the catalog, %d retired "
        "(404 at TMDB or id claimed by another item type)",
        summary["content_type"],
        summary["windows"],
        summary["split_windows"],
        summary["pages"],
        summary["enumerated"],
        summary["targets_total"],
        summary["targets_pending"],
        summary["targets_stuck"],
    )

    if summary["truncated_windows"]:
        logger.error(
            "seed %s: %d window(s) hit TMDB's 500-page cap even after the monthly "
            "split (%s) — the enumerated catalog is INCOMPLETE. Raise the vote "
            "threshold or add a finer slicing level before trusting this list.",
            summary["content_type"],
            summary["truncated_windows"],
            ", ".join(summary["truncated_labels"]),
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
