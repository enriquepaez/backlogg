"""Incremental catalog sync — ask each source what changed and write only that.

Feature 88.  Sibling of ``scripts/backfill_sync.py`` and
``scripts/seed_openlibrary_books.py``: it runs from GitHub Actions straight
against ``DATABASE_URL`` (Neon) and the external APIs, never through Render.
That is not a style choice.  The TMDB daily id export is a 28 MB gzip stream
and an Open Library dump edition is 17,5 GB; Render's free instance sleeps when
idle and caps a request at ~15 minutes, so neither could ever be an HTTP
endpoint.  Consequence: this adds **no HTTP surface**, so ``bruno/`` and
``docs/api.md`` do not change.

The four sources and their mechanisms
-------------------------------------

======  ===========================================================
movie   ``jobs.sync_movies_incremental`` — daily id export diff (new
        releases, gated on the release date), promotion sweep over
        ``/discover``, and ``/movie/changes`` for re-hydration
series  ``jobs.sync_series_incremental`` — the same three lanes on
        ``/tv/changes`` and ``tv_series_ids``
game    ``jobs.sync_games_incremental`` — ``where created_at > X``
        (new, gated on the ``game_type`` allowlist) and
        ``where updated_at > X`` (refresh what the catalog holds)
book    this script — diff of Open Library's monthly dump against the
        local catalog, skipped entirely while the published edition is
        the one already diffed
======  ===========================================================

Where each one resumes from lives in ``sync_watermarks`` (one row per source,
mechanism and item type), so re-running the script never redoes covered ground
and an interrupted run costs the difference, not the whole month.

Why the book lane is here and not in ``scheduler/jobs.py``
---------------------------------------------------------
Open Library publishes no changes feed this could use.  ``/recentchanges``
exists and is deliberately **not** used: the feature-73 quality filter is
computed from aggregates that only exist by walking the editions dump
(``readinglog_count``, ``edition_count``, ``number_of_pages_median``), and a
work arriving through ``/recentchanges`` carries none of them — it could not be
filtered, so it would enter behind the quality gate this very feature exists to
enforce.  The reasoning is written out in ``docs/seeding-plan.md`` §6.

So the book lane is a *dump diff*, and a dump diff is a batch job with a work
dir: it streams 17,5 GB and takes hours.  It stays in the script layer next to
the seeding it reuses (``scripts/seed_openlibrary_books.py --only-new``) rather
than becoming a coroutine in the nightly scheduler.

**It runs at most once per edition.**  Before anything is downloaded the script
resolves which edition ``ol_dump_*_latest.txt.gz`` currently points at (one
request, no body read) and compares it with the ``(OPEN_LIBRARY, MONTHLY_DUMP,
BOOK)`` watermark.  Equal means the diff already happened: the lane returns
immediately.  On 29 days out of 30 that is the entire cost of running the book
lane daily.

Isolation between sources
-------------------------
Each source runs in its own ``try``.  A failure is logged, recorded in the
summary and **does not stop the others** (checkpoint C19): they share nothing
but the database, they have independent watermarks by design, and a TMDB outage
must not be the reason IGDB went a day without news.

Usage::

    uv run python scripts/incremental_sync.py
    uv run python scripts/incremental_sync.py --source movie
    uv run python scripts/incremental_sync.py --source book --work-dir /tmp/olinc
    uv run python scripts/incremental_sync.py --skip book

Exit codes: 0 when every requested source ran clean; 2 when the run finished
**degraded** — a source failed or reported errors, and the catalog is therefore
less fresh than the green run would claim; 1 when the run could not be made at
all.  Same three-way split ``scripts/seed_openlibrary_books.py`` uses, and for
the same reason: a partial result must never be reported as a success.
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# The project is not an installed package: make `backlogg` importable when the
# script runs standalone (uv run python scripts/incremental_sync.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# ...and `scripts/` importable too, because the book lane reuses the five
# resumable phases of the seeding script instead of copying them. Importing the
# sibling is what keeps the dump pipeline a single implementation with a single
# set of tests; re-deriving the aggregates here would fork the feature-73
# filter into a second copy nobody would keep in step.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seed_openlibrary_books as ol_seed  # noqa: E402

from backlogg.books.adapters.openlibrary_dump import latest_dump_edition  # noqa: E402
from backlogg.core.database import async_session_factory, engine  # noqa: E402
from backlogg.scheduler import jobs  # noqa: E402
from backlogg.scheduler.repository import get_sync_watermark, set_sync_watermark  # noqa: E402

logger = logging.getLogger("incremental_sync")

DEFAULT_WORK_DIR = Path(".openlibrary-incremental")

# The Open Library watermark, spelled exactly as the model docstring reserves
# it (backlogg/shared/models.py::SyncWatermark).
OL_SOURCE = "OPEN_LIBRARY"
OL_KIND = "MONTHLY_DUMP"
OL_ITEM_TYPE = "BOOK"

SOURCES = ("movie", "series", "game", "book")

_JOB_NAMES: dict[str, str] = {
    "movie": "sync_movies_incremental",
    "series": "sync_series_incremental",
    "game": "sync_games_incremental",
}


# ── Open Library: the monthly dump diff ──────────────────────────────────────


async def _read_dump_watermark() -> str | None:
    """The dump edition the last successful diff covered, or None."""
    async with async_session_factory() as session:
        watermark = await get_sync_watermark(session, OL_SOURCE, OL_KIND, OL_ITEM_TYPE)
    return watermark.cursor_value if watermark else None


async def _advance_dump_watermark(edition: str) -> None:
    """Record ``edition`` as diffed, so the next run skips it."""
    async with async_session_factory() as session:
        await set_sync_watermark(session, OL_SOURCE, OL_KIND, OL_ITEM_TYPE, cursor_value=edition)
        await session.commit()


def _edition_still_published(edition: str) -> str:
    """Re-read the alias after the pass; ``edition`` again when it did not move.

    A lookup that *fails* is not treated as "it moved": that would throw away a
    finished 17,5 GB pass over a transient error on a request whose only job is
    to confirm something that is true 29 days out of 30.  It returns ``edition``
    (so the watermark advances, as it did before this check existed) and says so
    loudly — the check can only make the lane safer, never more fragile.
    """
    try:
        return latest_dump_edition().isoformat()
    except Exception as exc:
        logger.warning(
            "book: could not re-check the published dump edition after the pass "
            "(%s: %s) — assuming it is still %s and advancing the watermark",
            type(exc).__name__,
            exc,
            edition,
        )
        return edition


async def run_book_incremental(work_dir: Path, force: bool = False) -> dict:
    """Diff the current Open Library dump edition against the local catalog.

    Three steps, in this order for a reason:

    1. **Which edition is published?**  One request that reads no body.  If it
       equals the watermark the lane stops here, and that is the common case:
       the dumps are monthly and this script runs daily.  Downloading 17,5 GB to
       rediscover a catalog we already wrote would be the single most expensive
       mistake this feature could make.
    2. **The five phases**, in a work dir *named after the edition*.  That
       naming is what makes resuming safe across runs: an artifact can only ever
       be reused by a run of the same edition, so a crash in phase 3 costs
       phases 3-5 and never risks seeding last month's selection as if it were
       this month's.
    3. **Advance the watermark**, once the load phase has run *and* the alias
       still points at the edition step 1 resolved.  A run that dies in any
       earlier phase never reaches it: the watermark stays where it was and
       tomorrow's run resumes from its own artifacts.  Rows the loader
       *rejected* do not hold it back, and that asymmetry is the same one the
       TMDB lanes make — a rejected row is rejected deterministically, so
       blocking on it would wedge the lane for ever on a payload that is not
       going to change.  They surface in the exit code instead.

    Why step 3 re-checks the alias
    ------------------------------
    Steps 1 and 2 are two separate resolutions of the same moving pointer: the
    edition is read from ``ol_dump_works_latest.txt.gz``, and the five phases
    then download through that *same alias* again, hours later.  If Open
    Library published a new edition in between, the work dir would be named
    after one edition and hold another, and — the part that actually hurts —
    the watermark would advance to an edition this run never diffed, so the new
    one would be skipped for a month.

    Pinning the download to the URL step 1 already resolved would close the
    window at the front, and it was the first thing tried; it is **not** done
    here, for two reasons that are about Open Library and not about effort.
    The resolved URL is a redirect target on a specific archive.org node, not
    a stable address to re-request hours later for a 17,5 GB stream; and it
    names only the *works* dump, while the pass also streams reading-log,
    editions and authors through their own aliases — so pinning one file would
    leave three unpinned and buy an illusion.  Pinning all four would mean
    guessing archive.org's per-edition URL scheme and threading it through the
    five phases of ``scripts/seed_openlibrary_books.py``, i.e. risking the
    seeding path of feature 87 on an unverified URL shape.

    So the window is closed at the *back* instead, where it costs one request
    and no coupling: if the alias moved, the pass is reported and the watermark
    is left alone, and the next run re-diffs the new edition from a work dir
    named after it.  The mismatched dir is never read again (the alias only
    moves forward), so the workflow cache keeps its "the edition is in the
    path" premise for every dir a run actually consumes.

    ``force`` re-diffs an edition already covered (the write is an idempotent
    upsert, so it is safe; it is just not free).
    """
    start = time.monotonic()
    edition = latest_dump_edition().isoformat()
    covered = await _read_dump_watermark()

    if covered == edition and not force:
        logger.info(
            "book: dump edition %s already diffed — nothing downloaded (use --force to redo)",
            edition,
        )
        return {
            "edition": edition,
            "skipped": True,
            "reason": "edition_already_diffed",
            "elapsed_s": round(time.monotonic() - start, 1),
        }

    logger.info(
        "book: diffing dump edition %s against the catalog (last diffed: %s)",
        edition,
        covered or "never",
    )
    summary = await ol_seed.run(work_dir / edition, None, False, True)
    load = summary.get("load", {})

    published_now = _edition_still_published(edition)
    if published_now == edition:
        await _advance_dump_watermark(edition)
    else:
        logger.warning(
            "book: the dump alias moved from %s to %s while the pass was running — the "
            "work dir may mix editions, so the watermark stays at %s and the next run "
            "re-diffs %s from its own directory",
            edition,
            published_now,
            covered or "unset",
            published_now,
        )

    return {
        "edition": edition,
        "skipped": False,
        "previous_edition": covered,
        "edition_changed_mid_run": published_now != edition,
        "published_edition_after": published_now,
        "candidates": load.get("candidates", 0),
        "already_known": load.get("already_known", 0),
        "synced": load.get("synced", 0),
        "errors": load.get("errors", 0),
        "people_errors": load.get("people_errors", 0),
        "skipped_links": load.get("skipped_links", 0),
        "elapsed_s": round(time.monotonic() - start, 1),
    }


# ── Orchestration ────────────────────────────────────────────────────────────


async def run_incremental(sources: list[str], work_dir: Path, force: bool = False) -> dict:
    """Run the incremental of every requested source, isolating their failures.

    Sequential, not concurrent: movies, series and books all write through the
    same batch path into the same database, and the two TMDB jobs share one
    rate budget calibrated by ``TMDB_SEED_CONCURRENCY``.  Running them at once
    would multiply the in-flight requests without shortening the run that
    actually dominates the wall clock (the book lane, on the one day a month it
    does anything).
    """
    results: dict[str, dict] = {}
    failed: list[str] = []
    start = time.monotonic()

    for source in sources:
        logger.info("incremental %s: starting", source)
        try:
            if source == "book":
                results[source] = await run_book_incremental(work_dir, force)
            else:
                job = getattr(jobs, _JOB_NAMES[source])
                results[source] = await job()
        except Exception as exc:
            # C19: one source down is not four sources down. The failure is
            # recorded in the summary (not only in the log) because the exit
            # code is derived from it — a run that lost a source must not be
            # green.
            logger.exception("incremental %s: failed — the other sources continue", source)
            results[source] = {"failed": True, "error": f"{type(exc).__name__}: {exc}"}
            failed.append(source)
        else:
            logger.info("incremental %s: %s", source, results[source])

    return {
        "sources": results,
        "failed": failed,
        "errors": sum(int(result.get("errors", 0)) for result in results.values()),
        "synced": sum(int(result.get("synced", 0)) for result in results.values()),
        "elapsed_s": round(time.monotonic() - start, 1),
    }


async def _amain(sources: list[str], work_dir: Path, force: bool) -> dict:
    try:
        return await run_incremental(sources, work_dir, force)
    finally:
        await engine.dispose()


def _exit_code(summary: dict) -> int:
    """0 clean, 2 degraded. Never 0 for a run that lost a source."""
    if summary["failed"]:
        logger.error(
            "incremental: finished DEGRADED — source(s) %s failed. Their watermarks "
            "did not advance, so the next run covers the same ground; check the "
            "logs above before assuming the catalog is current.",
            ", ".join(summary["failed"]),
        )
        return 2
    if summary["errors"]:
        logger.error(
            "incremental: finished DEGRADED — %d item-level error(s). The catalog is "
            "less fresh than a green run would claim.",
            summary["errors"],
        )
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--source",
        action="append",
        choices=SOURCES,
        default=None,
        help="run only this source (repeatable). Default: all four",
    )
    parser.add_argument(
        "--skip",
        action="append",
        choices=SOURCES,
        default=[],
        help="skip this source (repeatable). Applied after --source",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help=f"parent dir of the per-edition Open Library artifacts "
        f"(default {DEFAULT_WORK_DIR}); each edition gets its own subdirectory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="book only — re-diff a dump edition already covered by the watermark",
    )
    args = parser.parse_args(argv)

    requested = args.source or list(SOURCES)
    sources = [source for source in SOURCES if source in requested and source not in args.skip]
    if not sources:
        parser.error("nothing to run: every requested source was skipped")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        summary = asyncio.run(_amain(sources, args.work_dir, args.force))
    except Exception:
        logger.exception("incremental: run failed unrecoverably")
        return 1

    logger.info(
        "incremental: finished — %d item(s) written across %s, %d error(s), %.0fs elapsed",
        summary["synced"],
        ", ".join(sources),
        summary["errors"],
        summary["elapsed_s"],
    )
    return _exit_code(summary)


if __name__ == "__main__":
    sys.exit(main())
