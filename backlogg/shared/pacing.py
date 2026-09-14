"""Outbound request pacing, shared by every adapter that has a published rate.

Extracted from ``backlogg.books.adapters.open_library`` when feature 79 added a
second paced source (the Wikidata SPARQL endpoint, which throttles by client).
The class is unchanged — only its address is new.  Copying it would have put
the same thirty lines in two adapters, which is the exact shape of the bug
``docs/conventions.md`` describes for the ASCII fold: it lived duplicated in
five modules and issue #18 had to be fixed in all five at once.

Each source keeps its **own module-level singleton**, because the budget
belongs to the source and not to a client instance: ``OpenLibraryClient`` is
built per call site (books service, search fan-out, nightly job) and a
per-instance pacer would let three of them issue 3x the allowance between them.
"""

import asyncio
import time

__all__ = ["RequestPacer"]


class RequestPacer:
    """Spaces outbound requests so no more than ``rps`` of them *start* per second.

    Why a pacer and not a semaphore: the on-demand paths are fan-outs, not page
    loops.  ``GET /books/{slug}`` resolves a work and then gathers one
    ``/authors/{olid}.json`` per author with ``asyncio.gather``, and the search
    fan-out queries every source at once — so the burst is concurrent and
    limiting *concurrency* would not limit the **rate**.

    Lock-free on purpose.  ``wait`` reserves its slot and only *then* awaits,
    with no ``await`` between reading and writing ``_next_at``; under asyncio's
    single-threaded scheduling that is atomic, so concurrent callers each get a
    distinct slot without a lock — and without a lock there is no object bound
    to an event loop, which a module-level singleton must avoid (an
    ``asyncio.Lock`` created under one loop raises when awaited under another,
    as every test that builds its own loop would).

    ``sleep`` and ``clock`` are injected so tests can assert the spacing
    without real time, and ``asyncio.sleep`` is captured **at construction**:
    several adapter tests patch ``asyncio.sleep`` globally to count tenacity
    backoffs, and the pacer must not show up in those counts.
    """

    __slots__ = ("_clock", "_next_at", "_sleep", "min_interval")

    def __init__(self, rps: float, *, clock=time.monotonic, sleep=asyncio.sleep) -> None:
        self.min_interval = 1.0 / rps if rps > 0 else 0.0
        self._clock = clock
        self._sleep = sleep
        self._next_at = 0.0

    async def wait(self) -> None:
        """Block until this caller's slot in the rate budget comes up."""
        if self.min_interval <= 0:
            return
        now = self._clock()
        start = max(now, self._next_at)
        self._next_at = start + self.min_interval
        delay = start - now
        if delay > 0:
            await self._sleep(delay)

    def reset(self) -> None:
        """Forget the reserved slots (tests only — the process has one pacer)."""
        self._next_at = 0.0
