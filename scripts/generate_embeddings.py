"""Generate the semantic vectors of the bounded subset (feature 75).

Sibling of ``scripts/sync_wikidata.py`` and ``scripts/backfill_sync.py``: a job
that runs **on the GitHub Actions runner against Neon**, never through Render.
Three independent reasons, and any one of them would be enough:

* the model (``sentence-transformers`` + torch) must not enter the image Render
  deploys — it is an optional extra precisely so that ``uv sync --no-dev``
  cannot pull it in;
* the free Render instance sleeps, has 512 MB and caps a request at ~15 min,
  while this walks tens of thousands of items;
* an embeddings API would do it without any of that, and cost money. The
  project runs on free tiers, and a runner's CPU is free.

It adds **no HTTP surface**: no admin endpoint, no ``bruno/`` request, nothing
in ``docs/api.md``.

Usage::

    uv sync --extra embeddings            # installs the model stack (NOT in prod)
    uv run python scripts/generate_embeddings.py
    uv run python scripts/generate_embeddings.py --item-type BOOK --item-type GAME
    uv run python scripts/generate_embeddings.py --max-items 5000
    uv run python scripts/generate_embeddings.py --force
    uv run python scripts/generate_embeddings.py --size-report   # measure only

Exit codes: 0 when the subset was walked to the end; 1 on an unrecoverable
failure; **2 when the run is incomplete** — the time budget expired mid-walk.
Like the other jobs in this repo, a partial pass is never reported as green.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# The project is not an installed package: make `backlogg` importable when the
# script runs standalone (uv run python scripts/generate_embeddings.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backlogg.core.config import settings  # noqa: E402
from backlogg.core.database import async_session_factory, engine  # noqa: E402
from backlogg.recommendations.adapters.local_embedder import (  # noqa: E402
    SentenceTransformerEmbedder,
)
from backlogg.recommendations.embeddings import (  # noqa: E402
    ITEM_TYPES,
    EmbeddingPassResult,
    format_quota_plan,
    format_storage_report,
    run_embedding_pass,
)
from backlogg.shared.item_embeddings import count_by_item_type, storage_report  # noqa: E402

logger = logging.getLogger("generate_embeddings")

#: The Neon free headroom this layer has to fit in: 512 MB of project quota
#: minus the 444-488 MB the full catalog is projected at (issue #28).
BUDGET_MB_LOW = 80
BUDGET_MB_HIGH = 120


def _log_result(result: EmbeddingPassResult) -> None:
    logger.info("embeddings: model %s, %d batch(es)", result.model, result.batches)
    logger.info("embeddings quota plan:")
    for line in format_quota_plan(result.quotas, result.available):
        logger.info("  %s", line)
    logger.info(
        "embeddings: %d selected — %d embedded (%d new, %d refreshed), %d unchanged and "
        "skipped, %d vanished mid-run",
        result.selected,
        result.embedded,
        result.created,
        result.updated,
        result.skipped_unchanged,
        result.vanished,
    )
    for item_type in ITEM_TYPES:
        counters = result.per_type.get(item_type)
        if counters is None:
            continue
        logger.info(
            "embeddings: %-7s selected=%d embedded=%d skipped=%d vanished=%d no_synopsis=%d",
            item_type,
            counters.selected,
            counters.embedded,
            counters.skipped_unchanged,
            counters.vanished,
            counters.without_overview,
        )
    logger.info(
        "embeddings: stored per type %s — %d of 4 types covered",
        {item_type: result.stored_by_type.get(item_type, 0) for item_type in ITEM_TYPES},
        result.types_covered,
    )
    if result.types_covered < 4:
        # Not a failure (a run restricted with --item-type legitimately covers
        # fewer), but it is the one invariant feature 80 depends on, so it is
        # never silent.
        logger.warning(
            "embeddings: only %d of the 4 content types carry vectors — feature 80's "
            "cross-type quota cannot be met with fewer",
            result.types_covered,
        )
    if not result.completed:
        logger.warning(
            "embeddings: the walk did NOT finish (time budget) — re-dispatch to continue; "
            "items already embedded are skipped, so nothing is redone"
        )


def _log_storage(result_storage) -> None:
    logger.info("item_embeddings on disk:")
    for line in format_storage_report(result_storage):
        logger.info("  %s", line)
    total_mb = result_storage.total_bytes / (1024 * 1024)
    verdict = "within" if total_mb <= BUDGET_MB_HIGH else "OVER"
    logger.info(
        "  budget       %s the %d-%d MB of Neon free headroom (issue #28)",
        verdict,
        BUDGET_MB_LOW,
        BUDGET_MB_HIGH,
    )
    if total_mb > BUDGET_MB_HIGH:
        logger.error(
            "item_embeddings is %.1f MB, past the %d MB headroom — lower "
            "EMBEDDING_MAX_ITEMS. Overrunning does not fail a test, it fails the "
            "nightly sync the day Neon refuses a write.",
            total_mb,
            BUDGET_MB_HIGH,
        )


async def _size_report_only() -> None:
    try:
        async with async_session_factory() as db:
            report = await storage_report(db)
            per_type = await count_by_item_type(db)
    finally:
        await engine.dispose()
    _log_storage(report)
    logger.info("stored per type: %s", per_type)


async def _amain(args: argparse.Namespace) -> EmbeddingPassResult:
    embedder = SentenceTransformerEmbedder(
        settings.EMBEDDING_MODEL, settings.EMBEDDING_DIM, device=args.device
    )
    try:
        return await run_embedding_pass(
            async_session_factory,
            embedder,
            item_types=args.item_types,
            max_items=args.max_items,
            batch_size=args.batch_size,
            budget_minutes=args.budget_minutes,
            force=args.force,
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--item-type",
        dest="item_types",
        action="append",
        choices=list(ITEM_TYPES),
        default=None,
        help="restrict the run to one content type (repeatable). The quota split is "
        "computed over all four regardless, so restricting never lets one type spend "
        "another's budget",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help=f"hard cap on how many items carry a vector, across all types (default "
        f"{settings.EMBEDDING_MAX_ITEMS}, env EMBEDDING_MAX_ITEMS)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help=f"items per inference batch and per transaction (default "
        f"{settings.EMBEDDING_BATCH_SIZE}, env EMBEDDING_BATCH_SIZE)",
    )
    parser.add_argument(
        "--budget-minutes",
        type=float,
        default=None,
        help="wall-clock ceiling for the run; 0 disables it (default "
        f"{settings.EMBEDDING_TIME_BUDGET_MINUTES}, env EMBEDDING_TIME_BUDGET_MINUTES)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-embed even items whose text and model are unchanged. Needed only when "
        "the serialisation itself changed; a new model is detected on its own",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="torch device for the model (default: let sentence-transformers choose)",
    )
    parser.add_argument(
        "--size-report",
        action="store_true",
        help="measure what item_embeddings costs on disk and exit, without loading the "
        "model or writing anything",
    )
    args = parser.parse_args(argv)
    if args.batch_size is not None and args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.max_items is not None and args.max_items < 0:
        parser.error("--max-items must not be negative")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.size_report:
        try:
            asyncio.run(_size_report_only())
        except Exception:
            logger.exception("embeddings: size report failed")
            return 1
        return 0

    try:
        result = asyncio.run(_amain(args))
    except Exception:
        logger.exception("embeddings: failed unrecoverably")
        return 1

    _log_result(result)
    if result.storage is not None:
        _log_storage(result.storage)
    return 0 if result.completed else 2


if __name__ == "__main__":
    sys.exit(main())
