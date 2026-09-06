"""Seed the book catalog from Open Library's monthly dumps (feature 87).

Sibling of ``scripts/seed_tmdb_targets.py``: enumeration and hydration of a
whole content type, run from GitHub Actions against Neon instead of from a
Render request (a full pass is ~1 h of wall clock and Render caps a request at
~15 min).  It adds no HTTP surface, so ``bruno/`` does not change.

Unlike the TMDB script this one also *writes the catalog rows*, and it can:
the dumps carry every field a book row needs, so there is no per-item
hydration request left to schedule.  That is also why books do **not** get a
``seed_targets`` work list — there is nothing to hydrate later.

What it does **not** touch: ``sync_books`` (the nightly job) still walks
``search.json`` with its cursor, and the on-demand fallback, ``search_book``
and ``get_book`` are untouched.  This changes the *seeding*, not the request
path.  The dump-based incremental is feature 88.

Five phases, each resumable
---------------------------
Every phase streams its dump straight from the socket (``httpx.stream`` +
``gzip``) — **no dump byte ever reaches the disk** — and leaves a small
artifact in ``--work-dir``.  A phase whose artifact already exists is skipped,
so a run that dies in phase 3 does not redo phases 1 and 2 (~13 GB of
download).  Artifacts are written to a temporary file and renamed, so a run
killed mid-write never leaves a truncated artifact for the next one to trust.

Phase 1  reading-log (0,12 GB) -> ``readinglog_counts.tsv.gz``
         ``COUNT(*)`` per work, kept for the works over the lower feature-73
         threshold: the whitelist everything downstream filters against.
Phase 2  editions (12,59 GB)   -> ``selected_works.jsonl.gz``
         per-work aggregates (edition count, languages, page median, ddc/lcc,
         isbn, first year) **and** the feature-73 filter: only the selected
         catalog is written out, which is what keeps phases 3-5 small.
Phase 3  works (4,06 GB)       -> ``work_records.jsonl.gz``
         title, subjects, cover, description and author keys.
Phase 4  authors (0,78 GB)     -> ``author_names.tsv.gz``
         the names behind those author keys, for the AUTHOR credits.
Phase 5  (no download)         -> the catalog itself
         upsert through the feature-84 batch writer.

Phase 5 needs no artifact of its own: the write is an upsert keyed by slug and
``external_ids``, so re-running it is idempotent by construction.

Usage::

    uv run python scripts/seed_openlibrary_books.py
    uv run python scripts/seed_openlibrary_books.py --work-dir /tmp/olseed
    uv run python scripts/seed_openlibrary_books.py --phase editions --force
    uv run python scripts/seed_openlibrary_books.py --phase load

Exit codes: 0 on success; 1 on an unrecoverable failure (network, dump format,
database); 2 when the run finished but is *degraded* — nothing selected, rows
rejected by the loader or external ids that could not be linked.  Like the
TMDB enumerator, a partial catalog must not be reported as a green run.
"""

import argparse
import asyncio
import gzip
import json
import logging
import os
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

# The project is not an installed package: make `backlogg` importable when the
# script runs standalone (uv run python scripts/seed_openlibrary_books.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backlogg.books import repository as books_repo  # noqa: E402
from backlogg.books.adapters.open_library import OpenLibraryClient  # noqa: E402
from backlogg.books.adapters.openlibrary_dump import (  # noqa: E402
    DUMP_AUTHORS,
    DUMP_EDITIONS,
    DUMP_READING_LOG,
    DUMP_WORKS,
    EditionAggregate,
    SelectedWork,
    WorkRecord,
    aggregate_editions,
    author_rows,
    build_search_doc,
    build_work_detail,
    collect_author_names,
    collect_work_records,
    count_reading_log,
    select_works,
    stream_dump_lines,
    whitelist_threshold,
)
from backlogg.core.database import async_session_factory, engine  # noqa: E402
from backlogg.scheduler.jobs import BatchWriter, refresh_catalog_search  # noqa: E402
from backlogg.shared.bulk_load import BulkItem  # noqa: E402
from backlogg.shared.external_ids import collect_link_skips  # noqa: E402

logger = logging.getLogger("seed_openlibrary_books")

DEFAULT_WORK_DIR = Path(".openlibrary-seed")

COUNTS_FILE = "readinglog_counts.tsv.gz"
SELECTED_FILE = "selected_works.jsonl.gz"
WORKS_FILE = "work_records.jsonl.gz"
AUTHORS_FILE = "author_names.tsv.gz"

PHASES = ("reading-log", "editions", "works", "authors", "load")

_ol_client = OpenLibraryClient()

# How often a long pass reports progress. Measured line counts on the
# 2026-08-31 dumps: 12,8 M (reading-log), 56,7 M (editions), 41,6 M (works),
# 15,4 M (authors), and the whole run is tens of minutes long — without a
# heartbeat an Actions run is indistinguishable from a hung one.
_PROGRESS_EVERY = 2_000_000


# ── Artifact I/O ─────────────────────────────────────────────────────────────


def _write_atomic(path: Path, lines: Iterable[str]) -> int:
    """Write gzipped lines to ``path`` via a temp file + rename.

    Atomicity is what makes "the artifact exists, so skip the phase" safe: a
    run killed mid-write leaves the ``.tmp`` behind, never a half artifact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    written = 0
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")
            written += 1
    os.replace(tmp, path)
    return written


def _read_lines(path: Path) -> Iterator[str]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            yield line.rstrip("\n")


def _progress(pass_name: str, start: float) -> Iterator[str]:
    """Wrap a dump stream with a heartbeat every ``_PROGRESS_EVERY`` lines."""
    count = 0
    for line in stream_dump_lines(pass_name):
        count += 1
        if count % _PROGRESS_EVERY == 0:
            logger.info(
                "%s: %d M lines read (%.0f s)",
                pass_name,
                count // 1_000_000,
                time.monotonic() - start,
            )
        yield line
    logger.info("%s: %d lines read in %.0f s", pass_name, count, time.monotonic() - start)


# ── Phase 1: reading-log ─────────────────────────────────────────────────────


def phase_reading_log(work_dir: Path) -> dict:
    start = time.monotonic()
    floor = whitelist_threshold()
    counts = count_reading_log(_progress(DUMP_READING_LOG, start), min_count=floor)
    written = _write_atomic(
        work_dir / COUNTS_FILE,
        (f"{work_id}\t{count}" for work_id, count in sorted(counts.items())),
    )
    return {
        "whitelist": written,
        "min_shelvings": floor,
        "elapsed_s": round(time.monotonic() - start, 1),
    }


def load_counts(work_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in _read_lines(work_dir / COUNTS_FILE):
        work_id, _, raw = line.partition("\t")
        if raw:
            counts[work_id] = int(raw)
    return counts


# ── Phase 2: editions ────────────────────────────────────────────────────────


def phase_editions(work_dir: Path) -> dict:
    start = time.monotonic()
    counts = load_counts(work_dir)
    aggregates = aggregate_editions(_progress(DUMP_EDITIONS, start), counts.keys())
    # ``select_works`` and not a loop written here: the test that proves the
    # feature-73 filter survives the move to dumps runs *that* function, so the
    # script has to run it too or the test would be validating a copy.
    selected = select_works(counts, aggregates)
    written = _write_atomic(
        work_dir / SELECTED_FILE,
        (
            json.dumps(
                {
                    "work_id": work.work_id,
                    "language": work.language,
                    "readinglog_count": work.readinglog_count,
                    "aggregate": work.aggregate.to_json(),
                },
                ensure_ascii=False,
            )
            for work in selected
        ),
    )
    return {
        "whitelisted": len(counts),
        "aggregated": len(aggregates),
        "selected": written,
        "elapsed_s": round(time.monotonic() - start, 1),
    }


def load_selected(work_dir: Path) -> dict[str, SelectedWork]:
    selected: dict[str, SelectedWork] = {}
    for line in _read_lines(work_dir / SELECTED_FILE):
        row = json.loads(line)
        raw = row["aggregate"]
        aggregate = EditionAggregate(
            edition_count=raw["edition_count"],
            languages=set(raw["languages"]),
            # The artifact stores the median, not the page counts it came from:
            # keeping ~19 k lists of per-edition page counts on disk to
            # recompute a number already computed would be pointless. A
            # one-element list round-trips it (median([m]) == m) and keeps the
            # dataclass the single definition of the field.
            pages=[raw["pages_median"]] if raw["pages_median"] is not None else [],
            ddc=raw["ddc"],
            lcc=raw["lcc"],
            isbn=raw["isbn"],
            first_publish_year=raw["first_publish_year"],
            cover_id=raw["cover_id"],
        )
        selected[row["work_id"]] = SelectedWork(
            work_id=row["work_id"],
            language=row["language"],
            readinglog_count=row["readinglog_count"],
            aggregate=aggregate,
        )
    return selected


# ── Phase 3: works ───────────────────────────────────────────────────────────


def phase_works(work_dir: Path) -> dict:
    start = time.monotonic()
    selected = load_selected(work_dir)
    records = collect_work_records(_progress(DUMP_WORKS, start), selected.keys())
    written = _write_atomic(
        work_dir / WORKS_FILE,
        (json.dumps(records[work_id].to_json(), ensure_ascii=False) for work_id in sorted(records)),
    )
    return {
        "selected": len(selected),
        "found": written,
        "missing": len(selected) - written,
        "elapsed_s": round(time.monotonic() - start, 1),
    }


def load_work_records(work_dir: Path) -> dict[str, WorkRecord]:
    records: dict[str, WorkRecord] = {}
    for line in _read_lines(work_dir / WORKS_FILE):
        row = json.loads(line)
        records[row["work_id"]] = WorkRecord(
            work_id=row["work_id"],
            title=row["title"],
            subjects=row["subjects"],
            cover_id=row["cover_id"],
            description=row["description"],
            author_ids=row["author_ids"],
        )
    return records


# ── Phase 4: authors ─────────────────────────────────────────────────────────


def phase_authors(work_dir: Path) -> dict:
    start = time.monotonic()
    records = load_work_records(work_dir)
    wanted = {author_id for record in records.values() for author_id in record.author_ids}
    names = collect_author_names(_progress(DUMP_AUTHORS, start), wanted)
    written = _write_atomic(
        work_dir / AUTHORS_FILE,
        (f"{author_id}\t{names[author_id]}" for author_id in sorted(names)),
    )
    return {
        "wanted": len(wanted),
        "found": written,
        "missing": len(wanted) - written,
        "elapsed_s": round(time.monotonic() - start, 1),
    }


def load_author_names(work_dir: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for line in _read_lines(work_dir / AUTHORS_FILE):
        author_id, _, name = line.partition("\t")
        if name:
            names[author_id] = name
    return names


# ── Phase 5: write the catalog ───────────────────────────────────────────────


def build_item(work: SelectedWork, record: WorkRecord, names: dict[str, str]) -> BulkItem | None:
    """Turn one work's artifacts into a catalog row, or ``None`` if unusable.

    The dict comes out of ``book_to_dict`` — the very mapper the on-demand
    path uses — so genres (feature 72), the slug and its issue-#18 fallback
    are computed by one implementation, not two.  A work whose title folds to
    nothing still gets a slug, because ``titled_slug`` falls back to the OL
    work id; a work with no title *at all* is dropped, because its row would
    have no display name.
    """
    data = _ol_client.book_to_dict(build_search_doc(work, record), build_work_detail(record))
    if not data.get("title"):
        return None
    return BulkItem(
        data=data,
        external_id=work.work_id,
        people=author_rows(record.author_ids, names),
    )


async def phase_load(work_dir: Path) -> dict:
    start = time.monotonic()
    selected = load_selected(work_dir)
    records = load_work_records(work_dir)
    names = load_author_names(work_dir)
    untitled = 0

    mapping_errors = 0

    with collect_link_skips() as link_skips:
        async with async_session_factory() as session:
            writer = BatchWriter(session, books_repo.BOOK_BULK_SPEC, "seed_openlibrary_books")
            for work_id in sorted(records):
                work = selected.get(work_id)
                if work is None:
                    continue
                try:
                    item = build_item(work, records[work_id], names)
                except Exception:
                    # Same graceful degradation ``sync_books`` has for its own
                    # mapping step: 17,5 GB of third-party data are exactly
                    # where a surprise comes from, and one unmappable work must
                    # cost that work, not the other 19.220 and the two hours of
                    # download behind them. Counted, logged, and it turns the
                    # run's exit code into 2 so it is never reported as green.
                    logger.exception("seed_openlibrary_books: error mapping work_id=%s", work_id)
                    mapping_errors += 1
                    continue
                if item is None:
                    untitled += 1
                    continue
                await writer.add(item)
            await writer.flush()
            try:
                await refresh_catalog_search(session)
            except Exception:
                logger.exception("seed_openlibrary_books: failed to refresh catalog_search")

    return {
        "candidates": len(records),
        "untitled": untitled,
        "synced": writer.synced,
        "errors": writer.errors + mapping_errors,
        "people_errors": writer.people_errors,
        "skipped_links": link_skips.count,
        "elapsed_s": round(time.monotonic() - start, 1),
    }


# ── Orchestration ────────────────────────────────────────────────────────────


_ARTIFACTS = {
    "reading-log": COUNTS_FILE,
    "editions": SELECTED_FILE,
    "works": WORKS_FILE,
    "authors": AUTHORS_FILE,
}


def _should_run(phase: str, work_dir: Path, only: str | None, force: bool) -> bool:
    if only is not None and only != phase:
        return False
    artifact = _ARTIFACTS.get(phase)
    if artifact is None or force:
        return True
    if (work_dir / artifact).exists():
        logger.info(
            "%s: artifact %s already present — skipping (use --force to redo)", phase, artifact
        )
        return False
    return True


async def run(work_dir: Path, only: str | None, force: bool) -> dict:
    """Run the requested phases in order and return one summary dict."""
    summary: dict = {"work_dir": str(work_dir)}
    try:
        for phase, runner in (
            ("reading-log", phase_reading_log),
            ("editions", phase_editions),
            ("works", phase_works),
            ("authors", phase_authors),
        ):
            if _should_run(phase, work_dir, only, force):
                logger.info("%s: starting", phase)
                summary[phase] = runner(work_dir)
                logger.info("%s: %s", phase, summary[phase])
        if only in (None, "load"):
            logger.info("load: starting")
            summary["load"] = await phase_load(work_dir)
            logger.info("load: %s", summary["load"])
    finally:
        await engine.dispose()
    return summary


def _exit_code(summary: dict) -> int:
    load = summary.get("load")
    if load is None:
        return 0
    if load["synced"] == 0:
        logger.error("load: 0 books written — the selected catalog is empty, nothing was seeded")
        return 2
    if load["errors"] or load["skipped_links"] or load["people_errors"]:
        logger.error(
            "load: finished DEGRADED — %d rejected rows, %d people errors, %d unlinked "
            "external ids. The catalog is incomplete; fix and re-run the load phase "
            "(it is idempotent).",
            load["errors"],
            load["people_errors"],
            load["skipped_links"],
        )
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help=f"where the per-phase artifacts live (default {DEFAULT_WORK_DIR})",
    )
    parser.add_argument(
        "--phase",
        choices=PHASES,
        default=None,
        help="run a single phase instead of all five",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-run a phase even if its artifact is already in the work dir",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        summary = asyncio.run(run(args.work_dir, args.phase, args.force))
    except Exception:
        logger.exception("seed_openlibrary_books: run failed unrecoverably")
        return 1

    logger.info("seed_openlibrary_books: finished — %s", summary)
    return _exit_code(summary)


if __name__ == "__main__":
    sys.exit(main())
