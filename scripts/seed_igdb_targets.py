"""Enumerate the IGDB catalog target list into ``seed_targets`` (feature 90).

This is the games half of the seeding split described in
``docs/seeding-plan.md`` §3, and the exact counterpart of
``scripts/seed_tmdb_targets.py``.  It answers one question — **which games
clear the quality filter** — and writes the answer to ``seed_targets``.  It
fetches no game detail and writes no catalog row; hydration is a separate pass
(``scripts/backfill_sync.py game`` / the nightly ``POST /admin/sync/game``),
driven by the difference between this list and ``external_ids``.

**A separate script rather than a flag on ``seed_tmdb_targets.py``**: that one
is TMDB in its name and in every line of its body — ``/discover`` pages, year
windows, monthly splitting, the 500-page guard, a ``--min-votes`` threshold and
an exit code 2 that means "a window was truncated".  IGDB has none of those
things: one keyset walk, no windows, no page cap, and a filter that is not a
tunable number.  Bending one script around two sources with nothing in common
but the destination table would make both harder to read than having two that
share the table, the repository functions and the shape of this docstring.

Method::

    fields id,rating_count,first_release_date;
    where game_type = (0,1,2,4,6,7,8,9) & rating > 0 & id > <last id seen>;
    sort id asc;
    limit 500;

The filter is feature 65's, unchanged: the ``game_type`` allowlist (no
bundles, mods, ports, packs or updates — issue #14) plus ``rating > 0``.
Measured against the live API on 2026-09-08: 337.291 games pass the allowlist
and **31.988** of those carry a rating.  At 500 per request that is **64
requests**; a full walk on 2026-09-09 took **52 s** and returned 32.000 ids
(the 4 req/s floor is 16 s, the rest is latency and the per-page commit).
``docs/operations.md`` recommends how often to re-run it and why.

**Keyset, not offset**, and not because offset fails — measured the same day,
``offset 31.900`` still answers and there is no 500-page cap as in TMDB.  It is
because ``rating > 0`` changes with no publication event at all: a player votes,
a game enters the set, and every page after the cursor shifts by one, so an
already-enumerated game silently drops out of the window.  That is the defect
that took ``/movie/popular`` out of the seeding path (``docs/seeding-plan.md``
§1).  A keyset cut is a concrete id and costs the same.

Re-running is safe and cheap: targets are upserted on
``(item_type, source, external_id)``, keeping their attempt counters, so a
re-enumeration only adds newly-qualifying games and refreshes the observed
``rating_count``/``release_year``.  Each page is persisted as it arrives, so an
interrupted run keeps everything it had already enumerated.

**This is also the promotion route.**  A game that had no rating when the
catalog was seeded and has one now enters by re-running this script — the same
role TMDB's promotion sweep plays.  Nothing else notices it: the nightly job
hydrates ``seed_targets`` and no longer re-walks any ranking.

Usage::

    uv run python scripts/seed_igdb_targets.py
    uv run python scripts/seed_igdb_targets.py --start-after 100000  # resume

Environment: ``TWITCH_CLIENT_ID`` and ``TWITCH_CLIENT_SECRET`` (IGDB auth via
Twitch client credentials).

Exit codes: 0 on success, 1 on an unrecoverable enumeration failure, 2 if the
walk stalled — a page came back with no id above the cursor, which cannot
happen with ``sort id asc`` and means the enumerated list is incomplete.  That
must not be reported as a green run.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# The project is not an installed package: make `backlogg` importable when the
# script runs standalone (uv run python scripts/seed_igdb_targets.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backlogg.core.config import settings  # noqa: E402
from backlogg.core.database import async_session_factory, engine  # noqa: E402
from backlogg.games.adapters.igdb import IGDB_PAGE_SIZE, IGDBClient  # noqa: E402
from backlogg.scheduler.discovery import DiscoveredTarget  # noqa: E402
from backlogg.scheduler.igdb_catalog import (  # noqa: E402
    IgdbEnumerationStats,
    enumerate_catalog,
)
from backlogg.scheduler.repository import (  # noqa: E402
    SeedTargetRow,
    count_seed_target_progress,
    count_seed_targets,
    upsert_seed_targets,
)

logger = logging.getLogger("seed_igdb_targets")

_SOURCE = "IGDB"
_ITEM_TYPE = "GAME"


async def _persist(targets: list[DiscoveredTarget]) -> None:
    """Sink for the enumerator: write one page's targets and commit.

    Committing per page is what makes the run resumable — an enumeration that
    dies on page 50 of 64 keeps the 49 pages it already wrote, and the ids it
    wrote are exactly the ones below its keyset cursor.
    """
    rows = [
        SeedTargetRow(
            item_type=_ITEM_TYPE,
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


async def run_enumeration(page_size: int, start_after: int) -> dict:
    """Enumerate the game catalog and return a summary dict."""
    client = IGDBClient()
    logger.info(
        "seed game: enumerating IGDB by keyset (page_size=%d, start_after=%d, source=%s)",
        page_size,
        start_after,
        _SOURCE,
    )

    stats: IgdbEnumerationStats = await enumerate_catalog(
        fetch_page=client.get_catalog_page,
        on_targets=_persist,
        page_size=page_size,
        start_after=start_after,
    )

    async with async_session_factory() as session:
        total = await count_seed_targets(session, _ITEM_TYPE, _SOURCE)
        progress = await count_seed_target_progress(
            session, _ITEM_TYPE, _SOURCE, max(1, settings.TMDB_SEED_MAX_ATTEMPTS)
        )

    return {
        "content_type": "game",
        "page_size": page_size,
        "start_after": start_after,
        "pages": stats.pages,
        "enumerated": stats.targets,
        "last_id": stats.last_id,
        "stalled": stats.stalled,
        "targets_total": total,
        "targets_pending": progress.pending,
        "targets_stuck": progress.stuck,
    }


async def _amain(page_size: int, start_after: int) -> dict:
    try:
        return await run_enumeration(page_size, start_after)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--page-size",
        type=int,
        default=IGDB_PAGE_SIZE,
        help=f"games per request (default and IGDB maximum {IGDB_PAGE_SIZE})",
    )
    parser.add_argument(
        "--start-after",
        type=int,
        default=0,
        help="resume the keyset walk after this IGDB id (default 0, the whole catalog)",
    )
    args = parser.parse_args(argv)

    if args.page_size < 1:
        parser.error(f"--page-size must be at least 1 (got {args.page_size})")
    if args.start_after < 0:
        parser.error(f"--start-after cannot be negative (got {args.start_after})")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        summary = asyncio.run(_amain(args.page_size, args.start_after))
    except Exception:
        logger.exception("seed game: enumeration failed unrecoverably")
        return 1

    logger.info(
        "seed game: finished — %d pages, %d results seen (last id %d), %d targets in the "
        "list, %d still missing from the catalog, %d retired (gone from IGDB or unlinkable)",
        summary["pages"],
        summary["enumerated"],
        summary["last_id"],
        summary["targets_total"],
        summary["targets_pending"],
        summary["targets_stuck"],
    )

    if summary["stalled"]:
        logger.error(
            "seed game: the keyset walk stalled at id %d — a page came back with no higher "
            "id, which cannot happen with 'sort id asc'. The enumerated catalog is "
            "INCOMPLETE; re-run with --start-after once the query is understood.",
            summary["last_id"],
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
