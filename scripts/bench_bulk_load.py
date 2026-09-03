"""Benchmark the per-item write path against the batch write path (feature 84).

Reports **two** numbers for each route, because they answer different
questions:

- **SQL round trips per item.** Counted with a ``before_cursor_execute``
  listener on the SQLAlchemy engine plus the COPY calls
  ``backlogg.shared.bulk_load`` issues straight on the raw asyncpg connection
  (they never reach the listener).  This is the deterministic, causal
  measurement: it is identical on a laptop and on Neon, and it is what makes
  the wall-clock difference *explainable* instead of anecdotal.
- **Wall clock and items/second.** The number that matters operationally, but
  only meaningful against a database with real latency: on localhost a round
  trip costs ~0,05 ms and on Neon ~40 ms, so the same round-trip count
  produces wildly different timings.  Run this against a DSN with latency to
  get the production figure.

Usage::

    # local (docker) — proves the round-trip reduction
    uv run python scripts/bench_bulk_load.py

    # against a database with real latency — proves the items/s
    uv run python scripts/bench_bulk_load.py --dsn "$BENCH_DATABASE_URL" \\
        --items 200 --credits 7 --batch-size 100

The DSN comes from ``--dsn`` or ``BENCH_DATABASE_URL`` and defaults to
``TEST_DATABASE_URL``.  Never pass a production DSN on the command line (it
lands in the shell history): export it into the environment instead.  The
script refuses to run against ``DATABASE_URL`` — the same guard
``tests/conftest.py`` applies — and deletes everything it wrote before
exiting unless ``--keep`` is given.

The rows it writes live in their own ``bench-*`` slug namespace and carry
external ids in the 99xxxxxx range, so they cannot collide with real catalog
data.
"""

import argparse
import asyncio
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

# The project is not an installed package: make `backlogg` importable when the
# script runs standalone (uv run python scripts/bench_bulk_load.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Engine, event, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from backlogg.core.config import settings  # noqa: E402
from backlogg.movies import repository as movies_repo  # noqa: E402
from backlogg.people import repository as people_repo  # noqa: E402
from backlogg.shared.bulk_load import (  # noqa: E402
    BulkItem,
    BulkPerson,
    bulk_load_items,
    copy_round_trips,
)
from backlogg.shared.external_ids import upsert_external_id  # noqa: E402

_SPEC = movies_repo.MOVIE_BULK_SPEC
_EXTERNAL_ID_BASE = 99_000_000


@dataclass
class Measurement:
    """What one route cost for ``items`` items."""

    route: str
    items: int
    statements: int
    copies: int
    seconds: float

    @property
    def round_trips(self) -> int:
        return self.statements + self.copies

    @property
    def per_item(self) -> float:
        return self.round_trips / self.items if self.items else 0.0

    @property
    def items_per_second(self) -> float:
        return self.items / self.seconds if self.seconds else 0.0


class _RoundTripCounter:
    """Counts every SQL round trip issued inside the ``with`` block."""

    def __init__(self) -> None:
        self.statements = 0
        self._baseline: dict[str, int] = {}
        self.copies = 0

    def __enter__(self) -> "_RoundTripCounter":
        self._baseline = dict(copy_round_trips)
        event.listen(Engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc_info) -> None:
        event.remove(Engine, "before_cursor_execute", self._record)
        self.copies = copy_round_trips["copy"] - self._baseline["copy"]

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements += 1


# ── Synthetic payloads ───────────────────────────────────────────────────────


def _payload(prefix: str, index: int) -> dict:
    title = f"Bench {prefix} {index}"
    return {
        "title": title,
        "original_title": title,
        "slug": f"bench-{prefix}-{index}",
        "overview": "Synthetic row written by scripts/bench_bulk_load.py.",
        "release_date": date(2020, 1, 1),
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": 1000,
        "revenue": 2000,
        "status": "Released",
        "rating_external": 7.5,
        "rating_count_external": 42,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Bench Drama", "slug": "bench-drama"}],
    }


def _people(prefix: str, index: int, credits: int) -> list[BulkPerson]:
    """Credits for one item.

    Half of them are shared across the whole run and half are unique to the
    item — roughly what a real TMDB slice looks like, and it keeps the person
    resolution from degenerating into "everything is already cached".
    """
    rows: list[BulkPerson] = []
    for position in range(credits):
        if position % 2 == 0:
            key = f"{prefix}-shared-{position}"
        else:
            key = f"{prefix}-{index}-{position}"
        rows.append(
            BulkPerson(
                source="TMDB",
                external_id=str(_EXTERNAL_ID_BASE + abs(hash(key)) % 1_000_000),
                name=f"Bench Person {key}",
                slug=f"bench-person-{key}",
                profile_url=None,
                role="ACTOR" if position else "DIRECTOR",
                character_name=f"Role {position}" if position else None,
                billing_order=position,
            )
        )
    return rows


def _items(prefix: str, count: int, credits: int) -> list[BulkItem]:
    return [
        BulkItem(
            data=_payload(prefix, index),
            external_id=str(_EXTERNAL_ID_BASE + 900_000 + index),
            people=_people(prefix, index, credits),
        )
        for index in range(count)
    ]


# ── The two routes ───────────────────────────────────────────────────────────


async def _run_per_item(session: AsyncSession, items: list[BulkItem]) -> None:
    """The pre-feature-84 route: one item at a time, two commits per item."""
    now = datetime.now(UTC)
    for item in items:
        movie = await movies_repo.upsert_movie(session, dict(item.data))
        await upsert_external_id(session, "MOVIE", movie.id, "TMDB", item.external_id)
        await session.commit()
        for person in item.people:
            row = await people_repo.get_or_create_person_by_external(
                session,
                person.source,
                person.external_id,
                person.name,
                person.slug,
                person.profile_url,
                now,
            )
            await people_repo.upsert_credit(
                session,
                {
                    "item_type": "MOVIE",
                    "item_id": movie.id,
                    "person_id": row.id,
                    "role": person.role,
                    "character_name": person.character_name,
                    "billing_order": person.billing_order,
                },
            )
        await session.commit()


async def _run_batch(session: AsyncSession, items: list[BulkItem], batch_size: int) -> None:
    """The feature-84 route: COPY + INSERT ... SELECT ... ON CONFLICT per batch."""
    for start in range(0, len(items), batch_size):
        await bulk_load_items(session, _SPEC, items[start : start + batch_size])
        await session.commit()
        session.expunge_all()


async def _measure(
    engine, route: str, items: list[BulkItem], batch_size: int | None
) -> Measurement:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        with _RoundTripCounter() as counter:
            start = time.monotonic()
            if batch_size is None:
                await _run_per_item(session, items)
            else:
                await _run_batch(session, items, batch_size)
            elapsed = time.monotonic() - start
    return Measurement(
        route=route,
        items=len(items),
        statements=counter.statements,
        copies=counter.copies,
        seconds=elapsed,
    )


# ── Cleanup ──────────────────────────────────────────────────────────────────


async def _cleanup(engine) -> None:
    """Delete every row the benchmark wrote (items, credits, people, genres)."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM credits WHERE item_type = 'MOVIE' AND item_id IN "
                "(SELECT id FROM movies WHERE slug LIKE 'bench-%')"
            )
        )
        await conn.execute(
            text(
                "DELETE FROM external_ids WHERE item_type = 'MOVIE' AND item_id IN "
                "(SELECT id FROM movies WHERE slug LIKE 'bench-%')"
            )
        )
        await conn.execute(
            text(
                "DELETE FROM movie_genres_join WHERE movie_id IN "
                "(SELECT id FROM movies WHERE slug LIKE 'bench-%')"
            )
        )
        await conn.execute(text("DELETE FROM movies WHERE slug LIKE 'bench-%'"))
        await conn.execute(text("DELETE FROM movie_genres WHERE slug LIKE 'bench-%'"))
        await conn.execute(
            text(
                "DELETE FROM credits WHERE person_id IN "
                "(SELECT id FROM people WHERE slug LIKE 'bench-person-%')"
            )
        )
        await conn.execute(
            text(
                "DELETE FROM external_ids WHERE item_type = 'PERSON' AND item_id IN "
                "(SELECT id FROM people WHERE slug LIKE 'bench-person-%')"
            )
        )
        await conn.execute(text("DELETE FROM people WHERE slug LIKE 'bench-person-%'"))


# ── Reporting ────────────────────────────────────────────────────────────────


def _report(dsn: str, credits: int, batch_size: int, results: list[Measurement]) -> str:
    host = urlsplit(dsn).hostname or "?"
    lines = [
        "",
        f"bulk_load benchmark — host={host}  credits/item={credits}  batch_size={batch_size}",
        "",
        f"{'route':<12}{'items':>7}{'stmts':>8}{'copy':>6}"
        f"{'round trips':>13}{'per item':>10}{'seconds':>10}{'items/s':>10}",
    ]
    for result in results:
        lines.append(
            f"{result.route:<12}{result.items:>7}{result.statements:>8}"
            f"{result.copies:>6}{result.round_trips:>13}"
            f"{result.per_item:>10.2f}{result.seconds:>10.2f}"
            f"{result.items_per_second:>10.1f}"
        )
    if len(results) == 2:
        before, after = results
        if after.per_item:
            lines.append(
                f"\nround trips per item: {before.per_item:.1f} -> {after.per_item:.2f} "
                f"({before.per_item / after.per_item:.0f}x fewer)"
            )
        if before.items_per_second:
            lines.append(
                f"items/s: {before.items_per_second:.1f} -> "
                f"{after.items_per_second:.1f} "
                f"({after.items_per_second / before.items_per_second:.1f}x faster)"
            )
    lines.append("")
    return "\n".join(lines)


# ── Entry point ──────────────────────────────────────────────────────────────


def _resolve_dsn(explicit: str | None) -> str:
    dsn = explicit or os.environ.get("BENCH_DATABASE_URL") or settings.TEST_DATABASE_URL
    dsn = dsn.strip()
    if not dsn:
        raise SystemExit("No DSN: pass --dsn, export BENCH_DATABASE_URL, or set TEST_DATABASE_URL.")
    if (urlsplit(dsn).hostname, urlsplit(dsn).path) == (
        urlsplit(settings.DATABASE_URL).hostname,
        urlsplit(settings.DATABASE_URL).path,
    ):
        raise SystemExit(
            "Refusing to benchmark against DATABASE_URL (the main database). "
            "Point --dsn/BENCH_DATABASE_URL at a scratch database."
        )
    return dsn


def _make_engine(dsn: str):
    connect_args: dict = {}
    if "sslmode" in dsn:
        dsn = re.sub(r"[?&]sslmode=\w+", "", dsn)
        connect_args["ssl"] = True
    return create_async_engine(dsn, echo=False, connect_args=connect_args)


async def _amain(args) -> str:
    dsn = _resolve_dsn(args.dsn)
    engine = _make_engine(dsn)
    try:
        await _cleanup(engine)
        results = [
            await _measure(engine, "per-item", _items("peritem", args.items, args.credits), None),
        ]
        await _cleanup(engine)
        results.append(
            await _measure(
                engine, "batch", _items("batch", args.items, args.credits), args.batch_size
            )
        )
        if not args.keep:
            await _cleanup(engine)
        return _report(dsn, args.credits, args.batch_size, results)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dsn", default=None, help="target DSN (default: TEST_DATABASE_URL)")
    parser.add_argument("--items", type=int, default=50, help="items written by each route")
    parser.add_argument("--credits", type=int, default=7, help="credits per item")
    parser.add_argument("--batch-size", type=int, default=None, help="items per batch")
    parser.add_argument(
        "--keep", action="store_true", help="do not delete the rows written by the run"
    )
    args = parser.parse_args(argv)
    if args.batch_size is None:
        args.batch_size = min(args.items, settings.BULK_LOAD_BATCH_SIZE)

    print(asyncio.run(_amain(args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
