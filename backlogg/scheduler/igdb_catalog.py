"""IGDB catalog enumeration by keyset (feature 90).

What this module is for
-----------------------

Until feature 90 games were the last content type still *enumerated* by a
cursor: ``sync_games`` walked IGDB's ``rating_count`` ranking by offset and
wrapped around at ``SEED_TOP_N_GAMES``.  That cost three things
(``backend_feature_list.json`` #90): a catalog capped at 10.000 rows over the
~32.000 games that actually pass the quality filter, a ``seed_top_n`` argument
that had to be kept in sync with a Render variable by hand, and a fourth way
of seeding where two are enough.

This module is the *enumeration* half of the replacement, the exact shape
``backlogg.scheduler.discovery`` has for TMDB: it answers one question —
**which games does the catalog want** — and streams the answer to a sink that
writes it into ``seed_targets``.  It fetches no game detail and writes no
catalog row; hydration is a separate pass driven by the difference between
that list and ``external_ids``.

The filter, and why it is the one it is
---------------------------------------

``IGDB_CATALOG_WHERE`` in the adapter: the ``game_type`` allowlist of feature
65 (no bundles, mods, ports, packs or updates — issue #14) **and**
``rating > 0``.  Measured against the live API on 2026-09-08: 337.291 games
pass the allowlist, **31.988** of those carry a rating.  This is the same bar
the ranking walk applied — it is not being loosened or tightened here, only
moved from "the first N of a ranking" to "every game that clears it".

Keyset, not offset
------------------

The walk is ``where ... & id > <last id seen>; sort id asc``, never
``offset N``.  Both work against IGDB — unlike TMDB there is no page cap, and
``offset 31.900`` was measured answering fine on 2026-09-08 — so this is a
correctness choice, not a workaround:

An offset walks a set that moves underneath it.  ``rating > 0`` changes with
no publication event at all: a player votes, a game crosses the threshold,
and every page after the cursor shifts by one, so an already-enumerated game
drops out of the window and is never seen again.  That is precisely the defect
that took ``/movie/popular`` out of the seeding path (``docs/seeding-plan.md``
§1) and it would be reintroduced here for no gain — a keyset cut is a concrete
id, it costs the same 64 requests, and it is resumable from a number the run
already knows.

Separation of concerns
----------------------

The adapter (``IGDBClient.get_catalog_page``) does one request and nothing
else.  This module owns the cursor, the throttle and the stopping rules, and
it never touches the database: it hands batches of :class:`DiscoveredTarget`
to an ``on_targets`` callback so the caller decides where they go — which is
what makes a run resumable (``scripts/seed_igdb_targets.py`` persists each
page as it arrives instead of holding 31.988 rows in memory and losing them on
a crash).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from backlogg.games.adapters.igdb import IGDB_PAGE_SIZE, IGDB_PAGE_THROTTLE_S
from backlogg.scheduler.discovery import DiscoveredTarget

logger = logging.getLogger(__name__)

# One page of the keyset walk: ``(after, limit) -> rows``.
CatalogPageFetcher = Callable[..., Awaitable[list[dict]]]
# Where the enumerated targets go.  Async so the sink can persist and commit.
TargetSink = Callable[[list[DiscoveredTarget]], Awaitable[None]]


@dataclass(slots=True)
class IgdbEnumerationStats:
    """Summary of one enumeration run — the numbers the operator needs.

    ``last_id`` is the keyset cursor the walk finished on.  It is reported
    (rather than kept private) because it is what a resumed run would restart
    from and what makes an interrupted enumeration auditable.

    ``stalled`` is the guard, not a statistic: it means a page came back whose
    highest id was not above the cursor, which cannot happen with
    ``sort id asc`` and would loop forever.  Anything but ``False`` here means
    the enumerated list is incomplete.
    """

    pages: int = 0
    targets: int = 0
    last_id: int = 0
    stalled: bool = False


def map_catalog_result(raw: dict) -> DiscoveredTarget | None:
    """Map one enumeration row to a target, or None if it carries no id.

    :class:`DiscoveredTarget` is reused verbatim rather than cloned for IGDB:
    ``vote_count`` carries IGDB's ``rating_count`` — the notoriety signal that
    orders the hydration work list, exactly the role TMDB's ``vote_count``
    plays — and ``release_year`` the year of ``first_release_date``.  A second
    identical dataclass would only make the two enumerations look unrelated.

    IGDB ships ``first_release_date`` as Unix seconds; the conversion is
    explicit (checkpoint C14) and a missing or malformed value costs the year,
    not the target: the game still deserves hydrating.
    """
    external_id = raw.get("id")
    if not external_id:
        return None

    release_year: int | None = None
    stamp = raw.get("first_release_date")
    if stamp is not None:
        try:
            release_year = datetime.fromtimestamp(int(stamp), tz=UTC).year
        except (TypeError, ValueError, OSError, OverflowError):
            release_year = None

    rating_count = raw.get("rating_count")
    return DiscoveredTarget(
        external_id=str(external_id),
        vote_count=int(rating_count) if rating_count is not None else None,
        release_year=release_year,
    )


async def enumerate_catalog(
    *,
    fetch_page: CatalogPageFetcher,
    on_targets: TargetSink,
    page_size: int = IGDB_PAGE_SIZE,
    throttle_s: float = IGDB_PAGE_THROTTLE_S,
    start_after: int = 0,
    stats: IgdbEnumerationStats | None = None,
) -> IgdbEnumerationStats:
    """Walk the whole catalog filter by keyset and stream targets to the sink.

    Sequential by construction: the next request needs the highest id of the
    previous answer, so there is nothing to fan out — and nothing to throttle
    beyond one ``asyncio.sleep`` between pages, which keeps the walk at ~3,3
    req/s against IGDB's 4.

    Three stopping rules, in this order:

    1. an **empty** page — the filter is exhausted;
    2. a **short** page (fewer rows than asked for) — the last page, emitted
       and then done;
    3. a **stalled** cursor — the page's highest id is not above the one asked
       for.  With ``sort id asc`` that is impossible, so it means the query
       came back wrong; stopping and reporting it beats spinning on the same
       page for ever.

    Failures are not swallowed: a page that still fails after the adapter's
    retries aborts the run.  The whole enumeration is 64 requests and 52 s
    (measured end to end on 2026-09-09; 16 s of that is the 4 req/s floor),
    and a half-enumerated catalog would be indistinguishable downstream from
    "those games no longer pass the filter" — silently shrinking the catalog is
    worse than stopping.
    """
    stats = stats if stats is not None else IgdbEnumerationStats(last_id=start_after)
    after = start_after
    size = max(1, min(page_size, IGDB_PAGE_SIZE))

    while True:
        rows = await fetch_page(after=after, limit=size)
        if not rows:
            break

        targets = [
            target for target in (map_catalog_result(raw) for raw in rows) if target is not None
        ]
        stats.pages += 1
        stats.targets += len(targets)
        if targets:
            await on_targets(targets)

        highest = max((int(raw["id"]) for raw in rows if raw.get("id")), default=after)
        if highest <= after:
            logger.error(
                "igdb enumeration: page after id=%d came back with no higher id (%d rows) — "
                "stopping; the enumerated list is INCOMPLETE",
                after,
                len(rows),
            )
            stats.stalled = True
            break
        after = highest
        stats.last_id = after

        if len(rows) < size:
            break
        await asyncio.sleep(throttle_s)

    return stats
