"""Direct backfill sync — run the slice-sync jobs in a loop, straight against the DB.

The nightly sync goes through ``POST /admin/sync/{type}`` on Render, whose
infrastructure caps each request at ~15 minutes, which forces a small nightly
slice (``SYNC_SLICE_SIZE`` / ``SYNC_SLICE_SIZE_<TYPE>``, ~100-350
items/night/type).  This script bypasses Render entirely: it reuses the exact
same job functions from ``backlogg.scheduler.jobs`` — same write path, same
``sync_cursors`` cursor — but runs them directly against ``DATABASE_URL`` and
the external APIs, iterating with a bigger slice until either:

- the persisted cursor wraps around to 0 (target reached or API exhausted), or
- a configurable time budget runs out (default 300 min, safely below the
  6 h GitHub Actions job limit).

Because progress is persisted in ``sync_cursors`` (shared with the nightly
sync), re-running the script resumes where the previous run stopped.

Since feature 84 those jobs write through the batch path
(``backlogg.shared.bulk_load``): items are still fetched one by one, but each
group of ``BULK_LOAD_BATCH_SIZE`` is written with a COPY into temp tables plus
``INSERT ... SELECT ... ON CONFLICT``, and every person of the batch is
resolved with a single query.  ``--slice-size`` passed here overrides both
``SYNC_SLICE_SIZE_<TYPE>`` and the global ``SYNC_SLICE_SIZE``; it controls how
much is fetched per iteration, while ``BULK_LOAD_BATCH_SIZE`` controls how
much is written per transaction (and therefore how much a batch fallback has
to redo).

Two modes (feature 85)
----------------------

**Ranking mode** (default) is everything described above: it walks the
external API's popular listing by offset and is, until feature 86 lands, the
only mass-seeding route the project has.

**Targeted credits mode** (``--only-missing-credits``) exists because the
ranking mode cannot close credit holes (issue #15): the items missing credits
came in through other paths (search fan-out, trending, ``/similar``) and sit
at arbitrary ranking positions or outside the ranking entirely, so 6.000
positions can be walked without touching a single one of them.  This mode
takes its work list from the **local catalog** instead — items with no rows
in ``credits``, joined to ``external_ids`` — so it converges by construction
and is bounded by the real hole.  It never fetches the item detail to
re-write the row (the row is already there), never touches ``sync_cursors``,
and stamps ``credits_synced_at`` after each successful fetch so items that
legitimately have no credits are not retried forever (``--recheck`` ignores
that stamp).  ``game`` is rejected: games have no people credits.

Usage::

    uv run python scripts/backfill_sync.py movie
    uv run python scripts/backfill_sync.py game --slice-size 500 --time-budget-minutes 300
    uv run python scripts/backfill_sync.py series --only-missing-credits
    uv run python scripts/backfill_sync.py movie --only-missing-credits --recheck

Environment overrides for the defaults: ``BACKFILL_SLICE_SIZE`` and
``BACKFILL_TIME_BUDGET_MINUTES``.

Exit codes: 0 on a normal stop (wraparound, exhausted gap list or time
budget), non-zero on an invalid content type or an unrecoverable sync
failure.
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# The project is not an installed package: make `backlogg` importable when the
# script runs standalone (uv run python scripts/backfill_sync.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backlogg.core.config import settings  # noqa: E402
from backlogg.core.database import async_session_factory, engine  # noqa: E402
from backlogg.scheduler import jobs  # noqa: E402
from backlogg.scheduler.repository import get_sync_offset  # noqa: E402

logger = logging.getLogger("backfill_sync")

DEFAULT_SLICE_SIZE = 500
DEFAULT_TIME_BUDGET_MINUTES = 300  # 5 h — below the 6 h GitHub Actions limit

_ITEM_TYPES: dict[str, str] = {
    "movie": "MOVIE",
    "series": "SERIES",
    "book": "BOOK",
    "game": "GAME",
}

_JOB_NAMES: dict[str, str] = {
    "movie": "sync_movies",
    "series": "sync_series",
    "book": "sync_books",
    "game": "sync_games",
}


class BackfillError(RuntimeError):
    """Raised when an iteration fails without syncing anything (no progress)."""


async def _read_cursor(item_type: str) -> int:
    """Return the persisted next offset for ``item_type`` (0 if absent)."""
    async with async_session_factory() as session:
        return await get_sync_offset(session, item_type)


async def run_backfill(content_type: str, slice_size: int, time_budget_s: float) -> dict:
    """Run the sync job for ``content_type`` in a loop until done or out of budget.

    Stops when the persisted cursor wraps around to 0 (target reached or the
    external API exhausted) or when ``time_budget_s`` elapses.  Raises
    :class:`BackfillError` if an iteration finishes with errors and zero
    synced items — retrying the same slice would loop forever.

    Returns a summary dict with ``content_type``, ``iterations``, ``synced``,
    ``errors``, ``people_errors``, ``next_offset``, ``elapsed_s`` and
    ``stop_reason`` (``"wraparound"`` or ``"time_budget"``).

    ``people_errors`` counts items whose credits could not be persisted while
    the item itself was upserted fine.  It used to be read off each job result
    and thrown away here (feature 85): a run in which *every* credits fetch
    failed still reported "6000 synced, 0 errors", and the only trace was a
    per-iteration log line.  ``sync_games`` does not report it (games carry no
    people credits), hence the ``.get`` default.
    """
    item_type = _ITEM_TYPES[content_type]
    # Resolved at call time (not captured in a dict) so tests can patch the job.
    job = getattr(jobs, _JOB_NAMES[content_type])

    start = time.monotonic()
    iterations = 0
    total_synced = 0
    total_errors = 0
    total_people_errors = 0
    stop_reason = "time_budget"
    next_offset = await _read_cursor(item_type)

    logger.info(
        "backfill %s: starting at offset %d (slice_size=%d, batch_size=%d, time_budget=%.0fs)",
        content_type,
        next_offset,
        slice_size,
        settings.BULK_LOAD_BATCH_SIZE,
        time_budget_s,
    )

    while True:
        iterations += 1
        result = await job(slice_size=slice_size)
        total_synced += result["synced"]
        total_errors += result["errors"]
        total_people_errors += result.get("people_errors", 0)

        if result["synced"] == 0 and result["errors"] > 0:
            raise BackfillError(
                f"backfill {content_type}: iteration {iterations} made no progress "
                f"({result['errors']} errors, 0 synced) — aborting"
            )

        next_offset = await _read_cursor(item_type)
        elapsed = time.monotonic() - start
        logger.info(
            "backfill %s: iteration %d — %d synced, %d errors, %d people_errors in %.1fs "
            "(slice offset %d, next offset %d, elapsed %.0fs)",
            content_type,
            iterations,
            result["synced"],
            result["errors"],
            result.get("people_errors", 0),
            result["duration_s"],
            result["offset"],
            next_offset,
            elapsed,
        )

        if next_offset == 0:
            stop_reason = "wraparound"
            break
        if elapsed >= time_budget_s:
            stop_reason = "time_budget"
            break

    return {
        "content_type": content_type,
        "iterations": iterations,
        "synced": total_synced,
        "errors": total_errors,
        "people_errors": total_people_errors,
        "next_offset": next_offset,
        "elapsed_s": round(time.monotonic() - start, 1),
        "stop_reason": stop_reason,
    }


async def run_credits_backfill(
    content_type: str, time_budget_s: float, recheck: bool = False
) -> dict:
    """Run the *targeted* credits backfill for ``content_type`` (feature 85).

    Delegates to ``jobs.sync_missing_credits``, which builds its work list
    from the local catalog (``LEFT JOIN credits ... WHERE NULL`` joined to
    ``external_ids``) instead of walking TMDB's popularity ranking.  Unlike
    the ranking mode there is no loop and no ``sync_cursors``: one pass over
    the gap list is the whole run, and it stops when the list is exhausted or
    the time budget expires.

    Raises :class:`BackfillError` when the run made no progress at all
    (nothing processed and at least one error) — same "do not report a broken
    run as green" guard the ranking mode has.
    """
    start = time.monotonic()
    logger.info(
        "backfill %s: starting targeted credits mode (recheck=%s, batch_size=%d, "
        "time_budget=%.0fs)",
        content_type,
        recheck,
        settings.BULK_LOAD_BATCH_SIZE,
        time_budget_s,
    )

    result = await jobs.sync_missing_credits(
        content_type, recheck=recheck, time_budget_s=time_budget_s
    )

    if result["processed"] == 0 and result["people_errors"] > 0:
        raise BackfillError(
            f"backfill {content_type}: targeted credits run made no progress "
            f"({result['people_errors']} people_errors, 0 processed) — aborting"
        )

    return {
        "content_type": content_type,
        "considered": result["considered"],
        "processed": result["processed"],
        "with_credits": result["with_credits"],
        "sealed_without_credits": result["sealed_without_credits"],
        "credits_written": result["credits_written"],
        "people_errors": result["people_errors"],
        "skipped_no_external_id": result["skipped_no_external_id"],
        "elapsed_s": round(time.monotonic() - start, 1),
        "stop_reason": result["stop_reason"],
    }


async def _amain(
    content_type: str,
    slice_size: int,
    time_budget_s: float,
    only_missing_credits: bool = False,
    recheck: bool = False,
) -> dict:
    try:
        if only_missing_credits:
            return await run_credits_backfill(content_type, time_budget_s, recheck)
        return await run_backfill(content_type, slice_size, time_budget_s)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("content_type", choices=sorted(_ITEM_TYPES))
    parser.add_argument(
        "--slice-size",
        type=int,
        default=int(os.environ.get("BACKFILL_SLICE_SIZE", DEFAULT_SLICE_SIZE)),
        help=f"items per sync iteration (default {DEFAULT_SLICE_SIZE}, env BACKFILL_SLICE_SIZE)",
    )
    parser.add_argument(
        "--time-budget-minutes",
        type=int,
        default=int(os.environ.get("BACKFILL_TIME_BUDGET_MINUTES", DEFAULT_TIME_BUDGET_MINUTES)),
        help=f"stop after this many minutes (default {DEFAULT_TIME_BUDGET_MINUTES}, "
        "env BACKFILL_TIME_BUDGET_MINUTES)",
    )
    parser.add_argument(
        "--only-missing-credits",
        action="store_true",
        help="targeted mode: work only on catalog items that have no credits, "
        "picked by a local query instead of the popularity cursor. Not "
        "available for 'game' (games have no people credits)",
    )
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="with --only-missing-credits, ignore credits_synced_at and re-visit "
        "items already looked up (default: skip them)",
    )
    args = parser.parse_args(argv)

    if args.recheck and not args.only_missing_credits:
        parser.error("--recheck only applies to --only-missing-credits")
    if args.only_missing_credits and args.content_type == "game":
        parser.error(
            "--only-missing-credits is not supported for 'game': games have no "
            "people-credit ingestion, only company credits that travel inside the "
            "item payload. Nothing would be backfilled."
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        summary = asyncio.run(
            _amain(
                args.content_type,
                args.slice_size,
                args.time_budget_minutes * 60,
                args.only_missing_credits,
                args.recheck,
            )
        )
    except Exception:
        logger.exception("backfill %s: failed unrecoverably", args.content_type)
        return 1

    if args.only_missing_credits:
        logger.info(
            "backfill %s: finished targeted credits mode (%s) — %d considered, "
            "%d processed, %d with credits, %d stamped without credits, "
            "%d credits written, %d people_errors, %d skipped (no external id), "
            "%.0fs elapsed",
            summary["content_type"],
            summary["stop_reason"],
            summary["considered"],
            summary["processed"],
            summary["with_credits"],
            summary["sealed_without_credits"],
            summary["credits_written"],
            summary["people_errors"],
            summary["skipped_no_external_id"],
            summary["elapsed_s"],
        )
        return 0

    logger.info(
        "backfill %s: finished (%s) — %d iterations, %d synced, %d errors, "
        "%d people_errors, next offset %d, %.0fs elapsed",
        summary["content_type"],
        summary["stop_reason"],
        summary["iterations"],
        summary["synced"],
        summary["errors"],
        summary.get("people_errors", 0),
        summary["next_offset"],
        summary["elapsed_s"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
