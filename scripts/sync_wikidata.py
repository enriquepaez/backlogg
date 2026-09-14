"""Volcado mensual de Wikidata: ancla de QID + adaptaciones (feature 79).

Sibling of ``scripts/seed_tmdb_targets.py`` and
``scripts/seed_openlibrary_books.py``: a job that runs **on the GitHub Actions
runner against Neon**, not through Render.

Why not an admin endpoint, since the feature says "following the pattern of
``nightly-sync.yml``": that pattern is about *scheduling* (a cron plus a
``workflow_dispatch``), and this job borrows exactly that.  Its *execution*
cannot go the same way — ``nightly-sync.yml`` curls
``POST /v1/admin/sync/{type}`` and Render's free instance sleeps when idle,
has 512 MB and caps a request at ~15 min, while the anchor pass walks every
externally-linked item in the catalog.  So it takes the road
``scripts/backfill_sync.py`` already opened, and adds **no HTTP surface** —
``bruno/`` and ``docs/api.md`` are untouched by this feature.

Two passes, in this order and for a reason (see
``backlogg/recommendations/wikidata_sync.py``): the anchor has to exist before
a relation can resolve its far end **by id**.  Running ``--pass relations`` on
a catalog with no anchor is not an error, it simply finds nothing.

Usage::

    uv run python scripts/sync_wikidata.py                 # anchor, then relations
    uv run python scripts/sync_wikidata.py --pass anchor
    uv run python scripts/sync_wikidata.py --pass relations
    uv run python scripts/sync_wikidata.py --item-type BOOK --batch-size 200
    uv run python scripts/sync_wikidata.py --budget-minutes 240

Exit codes: 0 when both passes finished their walk; 1 on an unrecoverable
failure; **2 when the run is incomplete or degraded** — the time budget
expired mid-walk, or links/identities were skipped (issues #22 / #24).  Like
the other seeding scripts, a partial pass must not be reported as a green run.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# The project is not an installed package: make `backlogg` importable when the
# script runs standalone (uv run python scripts/sync_wikidata.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backlogg.core.config import settings  # noqa: E402
from backlogg.core.database import async_session_factory, engine  # noqa: E402
from backlogg.recommendations.adapters.wikidata import (  # noqa: E402
    ANCHOR_PROPERTIES,
    WIKIDATA_QID_BATCH,
    WIKIDATA_VALUES_BATCH,
)
from backlogg.recommendations.wikidata_sync import (  # noqa: E402
    AnchorPassResult,
    RelationsPassResult,
    format_coverage_report,
    run_anchor_pass,
    run_relations_pass,
)

logger = logging.getLogger("sync_wikidata")

PASSES = ("all", "anchor", "relations")


def _log_anchor(result: AnchorPassResult) -> None:
    # The four buckets partition ``considered`` exactly, so the line reconciles
    # with the table: ``anchored`` counts links that actually landed on this
    # item, never attempts (see ``run_anchor_pass``).
    logger.info(
        "wikidata anchor: %d item(s) considered in %d batch(es) — %d anchored, %d not in "
        "Wikidata, %d ambiguous (id claimed by more than one entity), %d unlinked "
        "(the QID was already taken by another item of the same type)",
        result.considered,
        result.batches,
        result.resolved,
        result.missing,
        result.ambiguous,
        result.unlinked,
    )
    for item_type, counters in result.per_type.items():
        logger.info(
            "wikidata anchor: %-7s considered=%d anchored=%d missing=%d ambiguous=%d unlinked=%d",
            item_type,
            counters["considered"],
            counters["resolved"],
            counters["missing"],
            counters["ambiguous"],
            counters["unlinked"],
        )
    # The coverage report the acceptance list asks for, per item type.
    logger.info("wikidata anchor coverage by item type:")
    for line in format_coverage_report(result.coverage):
        logger.info("  %s", line)
    if result.skipped_links:
        logger.warning(
            "wikidata anchor: %d QID link(s) skipped — the QID was already claimed by "
            "another item of the same type, so this item keeps no anchor (issue #22)",
            result.skipped_links,
        )
    if result.skipped_identities:
        logger.warning(
            "wikidata anchor: %d QID(s) dropped — the item already held a different "
            "WIKIDATA id and uq_item_source only fits one (issue #24)",
            result.skipped_identities,
        )
    if not result.completed:
        logger.warning(
            "wikidata anchor: the walk did NOT finish (time budget) — the cursor is kept, "
            "re-dispatch to continue where it stopped"
        )


def _log_relations(result: RelationsPassResult) -> None:
    logger.info(
        "wikidata relations: %d anchored item(s) read in %d batch(es) — %d statement(s), "
        "%d edge(s) written (%d new, %d refreshed), %d end(s) not in the catalog, "
        "%d self-edge(s) dropped",
        result.anchored_read,
        result.batches,
        result.statements,
        result.written,
        result.created,
        result.updated,
        result.unmatched_ends,
        result.self_edges,
    )
    for relation, count in sorted(result.per_relation.items()):
        logger.info("wikidata relations: %-12s %d edge(s)", relation, count)
    if not result.completed:
        logger.warning(
            "wikidata relations: the walk did NOT finish (time budget) — the cursor is "
            "kept, re-dispatch to continue where it stopped"
        )


async def _amain(
    args: argparse.Namespace,
) -> tuple[AnchorPassResult | None, RelationsPassResult | None]:
    anchor: AnchorPassResult | None = None
    relations: RelationsPassResult | None = None
    try:
        if args.selected_pass in ("all", "anchor"):
            anchor = await run_anchor_pass(
                async_session_factory,
                item_types=args.item_types,
                batch_size=args.batch_size,
                budget_minutes=args.budget_minutes,
            )
        if args.selected_pass in ("all", "relations"):
            relations = await run_relations_pass(
                async_session_factory,
                batch_size=args.relations_batch_size,
                budget_minutes=args.budget_minutes,
            )
    finally:
        await engine.dispose()
    return anchor, relations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--pass",
        dest="selected_pass",
        choices=PASSES,
        default="all",
        help="which pass to run (default: all — anchor first, then relations)",
    )
    parser.add_argument(
        "--item-type",
        dest="item_types",
        action="append",
        choices=sorted(ANCHOR_PROPERTIES),
        default=None,
        help="restrict the anchor pass to one content type (repeatable)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=WIKIDATA_VALUES_BATCH,
        help=f"external ids per SPARQL VALUES block in the anchor pass "
        f"(default {WIKIDATA_VALUES_BATCH})",
    )
    parser.add_argument(
        "--relations-batch-size",
        type=int,
        default=WIKIDATA_QID_BATCH,
        help=f"QIDs per SPARQL VALUES block in the relations pass (default {WIKIDATA_QID_BATCH})",
    )
    parser.add_argument(
        "--budget-minutes",
        type=float,
        default=settings.WIKIDATA_SYNC_TIME_BUDGET_MINUTES,
        help="wall-clock ceiling per pass; 0 disables it (default "
        f"{settings.WIKIDATA_SYNC_TIME_BUDGET_MINUTES}, env "
        "WIKIDATA_SYNC_TIME_BUDGET_MINUTES)",
    )
    args = parser.parse_args(argv)
    if args.batch_size <= 0 or args.relations_batch_size <= 0:
        parser.error("batch sizes must be positive")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        anchor, relations = asyncio.run(_amain(args))
    except Exception:
        logger.exception("wikidata sync: failed unrecoverably")
        return 1

    degraded = False
    if anchor is not None:
        _log_anchor(anchor)
        degraded |= not anchor.completed
        degraded |= bool(anchor.skipped_links or anchor.skipped_identities)
    if relations is not None:
        _log_relations(relations)
        degraded |= not relations.completed
    return 2 if degraded else 0


if __name__ == "__main__":
    sys.exit(main())
