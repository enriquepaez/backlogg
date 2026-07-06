"""Direct backfill sync — run the slice-sync jobs in a loop, straight against the DB.

The nightly sync goes through ``POST /admin/sync/{type}`` on Render, whose
infrastructure caps each request at ~15 minutes, which forces a small
``SYNC_SLICE_SIZE`` (~100 items/night/type).  This script bypasses Render
entirely: it reuses the exact same job functions from
``backlogg.scheduler.jobs`` (same upsert logic, same ``sync_cursors``
cursor) but runs them directly against ``DATABASE_URL`` and the external
APIs, iterating with a bigger slice until either:

- the persisted cursor wraps around to 0 (target reached or API exhausted), or
- a configurable time budget runs out (default 300 min, safely below the
  6 h GitHub Actions job limit).

Because progress is persisted in ``sync_cursors`` (shared with the nightly
sync), re-running the script resumes where the previous run stopped.

Usage::

    uv run python scripts/backfill_sync.py movie
    uv run python scripts/backfill_sync.py game --slice-size 500 --time-budget-minutes 300

Environment overrides for the defaults: ``BACKFILL_SLICE_SIZE`` and
``BACKFILL_TIME_BUDGET_MINUTES``.

Exit codes: 0 on a normal stop (wraparound or time budget), non-zero on an
invalid content type or an unrecoverable sync failure.
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
    ``errors``, ``next_offset``, ``elapsed_s`` and ``stop_reason``
    (``"wraparound"`` or ``"time_budget"``).
    """
    item_type = _ITEM_TYPES[content_type]
    # Resolved at call time (not captured in a dict) so tests can patch the job.
    job = getattr(jobs, _JOB_NAMES[content_type])

    start = time.monotonic()
    iterations = 0
    total_synced = 0
    total_errors = 0
    stop_reason = "time_budget"
    next_offset = await _read_cursor(item_type)

    logger.info(
        "backfill %s: starting at offset %d (slice_size=%d, time_budget=%.0fs)",
        content_type,
        next_offset,
        slice_size,
        time_budget_s,
    )

    while True:
        iterations += 1
        result = await job(slice_size=slice_size)
        total_synced += result["synced"]
        total_errors += result["errors"]

        if result["synced"] == 0 and result["errors"] > 0:
            raise BackfillError(
                f"backfill {content_type}: iteration {iterations} made no progress "
                f"({result['errors']} errors, 0 synced) — aborting"
            )

        next_offset = await _read_cursor(item_type)
        elapsed = time.monotonic() - start
        logger.info(
            "backfill %s: iteration %d — %d synced, %d errors in %.1fs "
            "(slice offset %d, next offset %d, elapsed %.0fs)",
            content_type,
            iterations,
            result["synced"],
            result["errors"],
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
        "next_offset": next_offset,
        "elapsed_s": round(time.monotonic() - start, 1),
        "stop_reason": stop_reason,
    }


async def _amain(content_type: str, slice_size: int, time_budget_s: float) -> dict:
    try:
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
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        summary = asyncio.run(
            _amain(args.content_type, args.slice_size, args.time_budget_minutes * 60)
        )
    except Exception:
        logger.exception("backfill %s: failed unrecoverably", args.content_type)
        return 1

    logger.info(
        "backfill %s: finished (%s) — %d iterations, %d synced, %d errors, "
        "next offset %d, %.0fs elapsed",
        summary["content_type"],
        summary["stop_reason"],
        summary["iterations"],
        summary["synced"],
        summary["errors"],
        summary["next_offset"],
        summary["elapsed_s"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
