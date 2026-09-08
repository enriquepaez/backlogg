"""TMDB daily id exports — the "what is new today" feed (feature 88).

What this module is for
-----------------------

The catalog of movies and series is *defined* by a quality threshold
(``vote_count >= 25``, feature 86) and enumerated through ``/discover``.  That
works for everything that already has votes and is structurally blind to one
case: **a release has no votes on the day it comes out**, so it can never
appear in a ``vote_count.gte`` enumeration and would enter the catalog only
months later, if at all.

TMDB publishes, once a day, the complete list of ids it holds::

    https://files.tmdb.org/p/exports/movie_ids_MM_DD_YYYY.json.gz
    https://files.tmdb.org/p/exports/tv_series_ids_MM_DD_YYYY.json.gz

Gzipped JSONL — one JSON object per line, not a JSON array — with ``id``,
``original_title``/``original_name``, ``popularity``, ``adult`` and ``video``
(28 MB and 5 MB compressed, measured 2026-09-02).  Comparing today's file
against the one we last processed gives the ids that **appeared**, which is
the only cheap signal of a new release TMDB offers.  That is this module's
whole job; the quality gate those ids still have to clear lives in
``backlogg.scheduler.discovery`` and the orchestration in
``backlogg.scheduler.jobs``.

Three facts about the files that shape the API
----------------------------------------------

1. **Publication time.**  The export for day *D* starts being generated at
   ~07:00 UTC and is available at ~08:00 UTC.  A run before that hour must ask
   for *D-1* or it gets a 404 — :func:`latest_export_date` is that rule, and it
   is a function rather than an inline ``date.today()`` precisely so it can be
   tested without waiting for tomorrow.
2. **Retention is three months.**  Older files are gone, so a baseline older
   than :data:`EXPORT_RETENTION_DAYS` cannot be re-fetched and the diff has no
   "before" side.  That is reported as :class:`ExportUnavailable` rather than
   guessed at.
3. **Adult entries live in separate files** (``adult_movie_ids_*``), which the
   catalog does not ingest.  The ``adult`` flag is still checked on every row:
   a mislabelled entry in the main file must not slip in just because it was
   filed in the wrong place.

Streaming, never disk
---------------------

The same shape as ``backlogg.books.adapters.openlibrary_dump.stream_dump_lines``
— an ``httpx`` byte iterator wrapped into a file-like object, handed to
``gzip.GzipFile``, decoded line by line — for the same reasons: the body does
not fit anywhere sensible, and gzip has no seek point, so a failure *before*
the first line is free to retry while a failure mid-stream is not (retrying it
would re-emit the lines already handed out).  ``_ChunkReader``/``_text_lines``
are a deliberate copy of that adapter's helpers rather than an import: they are
private helpers of a *books* adapter, and reaching across a vertical slice for
an underscore-prefixed name would be a worse coupling than 25 duplicated lines.
If a third caller ever needs them, that is the moment to hoist them into
``backlogg/shared/``.

Synchronous on purpose
----------------------

Like the Open Library passes: this is a network/CPU loop that does no database
work.  The async job calls it through ``asyncio.to_thread`` so the download
does not block the event loop, instead of colouring the whole file async for a
single ``await``.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import IO, Any

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "EXPORT_MOVIES",
    "EXPORT_PUBLISH_HOUR_UTC",
    "EXPORT_RETENTION_DAYS",
    "EXPORT_SERIES",
    "ExportEntry",
    "ExportUnavailable",
    "collect_appeared_entries",
    "export_url",
    "latest_export_date",
    "load_export_ids",
    "parse_export_line",
    "stream_export_entries",
    "stream_export_lines",
]

# The two files the catalog cares about. ``person_ids``, ``collection_ids``,
# ``keyword_ids`` and the ``adult_*`` variants exist and are not ingested.
EXPORT_MOVIES = "movie_ids"
EXPORT_SERIES = "tv_series_ids"

_EXPORT_URL = "https://files.tmdb.org/p/exports/{name}_{day}.json.gz"

# Generation starts at ~07:00 UTC and the file is served from ~08:00 UTC.
# A run earlier than this must ask for the previous day.
EXPORT_PUBLISH_HOUR_UTC = 8

# TMDB keeps three months of daily exports. A baseline older than this cannot
# be downloaded again, so the "what appeared" diff has nothing to compare with.
EXPORT_RETENTION_DAYS = 90

_EXPORT_TIMEOUT = httpx.Timeout(120.0, connect=30.0)
_EXPORT_HEADERS = {
    "User-Agent": "backlogg/1.0 (https://github.com/enriquepaez/backlogg; contact@backlogg.app)",
}
_CHUNK_SIZE = 1 << 20

# Attempts to *open* an export stream. Applies only while no line has been
# handed out yet — see ``stream_export_lines``.
_EXPORT_CONNECT_ATTEMPTS = 3
_EXPORT_RETRY_BACKOFF_S = 5.0

# What counts as "the download failed" rather than "the file is wrong".
# ``EOFError``/``BadGzipFile`` are here because a body that ends early is a cut
# connection seen one layer up. A 404 is *not* here: it is not transient, it
# means the file does not exist (yet, or any more), and it is raised as
# ``ExportUnavailable`` so the caller can tell the two apart.
_RETRYABLE_STREAM_ERRORS = (
    httpx.TransportError,
    httpx.HTTPStatusError,
    EOFError,
    gzip.BadGzipFile,
)


class ExportUnavailable(RuntimeError):
    """TMDB has no export file for that name and day (HTTP 404).

    Two legitimate causes, and the caller has to handle both: the day is older
    than the three-month retention, or today's file has not been published yet
    (a run started before ~08:00 UTC that asked for today anyway).
    """


@dataclass(frozen=True, slots=True)
class ExportEntry:
    """One line of a daily id export.

    Everything the file carries and nothing else.  There is **no release date
    and no vote count here** — that is the reason the quality gate needs the
    detail request; this payload alone cannot tell a new release from a
    decades-old entry someone just created.
    """

    external_id: str
    title: str
    popularity: float
    adult: bool
    video: bool


def export_url(name: str, day: date) -> str:
    """URL of the ``name`` export for ``day`` (``MM_DD_YYYY`` in the filename)."""
    return _EXPORT_URL.format(name=name, day=f"{day.month:02d}_{day.day:02d}_{day.year:04d}")


def latest_export_date(now: datetime) -> date:
    """The most recent export day that is certain to exist at ``now``.

    Before :data:`EXPORT_PUBLISH_HOUR_UTC` today's file is still being
    generated, so the answer is yesterday.  ``now`` must be timezone-aware and
    is converted to UTC here: the publication hour is a UTC fact, and reading
    it in a local clock is how a nightly job in Europe/Madrid would ask for a
    file that does not exist yet for two hours every day.
    """
    if now.tzinfo is None:
        raise ValueError(f"latest_export_date: now must be timezone-aware, got {now!r}")
    moment = now.astimezone(UTC)
    if moment.hour >= EXPORT_PUBLISH_HOUR_UTC:
        return moment.date()
    return moment.date() - timedelta(days=1)


class _ChunkReader(io.RawIOBase):
    """Minimal file-like view over an ``httpx`` byte iterator.

    ``gzip.GzipFile`` needs an object with ``read(n)``; ``httpx`` gives an
    iterator of chunks.  Wrapping instead of buffering the whole body is the
    point: the movies export is 28 MB compressed and ~40 MB of JSONL, and
    nothing is ever written to disk.
    """

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = iter(chunks)
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        size = min(len(buffer), len(self._buffer))
        buffer[:size] = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return size


def _text_lines(chunks: Iterable[bytes]) -> Iterator[str]:
    """Decompress a gzip byte stream and yield its lines, newline stripped."""
    raw: IO[bytes] = io.BufferedReader(_ChunkReader(chunks))  # type: ignore[arg-type]
    with gzip.GzipFile(fileobj=raw) as gz:
        for line in io.TextIOWrapper(gz, encoding="utf-8", errors="replace"):
            yield line.rstrip("\n")


def stream_export_lines(name: str, day: date) -> Iterator[str]:
    """Stream one daily export line by line, decompressing on the fly.

    Retries **only before the first line is yielded**.  Opening the stream
    again costs nothing; a failure mid-stream cannot be resumed (gzip has no
    seek point) and restarting would feed the caller the same million lines
    twice, inflating the diff with ids it has already seen.

    A 404 raises :class:`ExportUnavailable` immediately instead of burning the
    retry budget: "this file does not exist" is an answer, not a failure.
    """
    url = export_url(name, day)
    with httpx.Client(
        headers=_EXPORT_HEADERS, timeout=_EXPORT_TIMEOUT, follow_redirects=True
    ) as client:
        for attempt in range(1, _EXPORT_CONNECT_ATTEMPTS + 1):
            produced = 0
            try:
                with client.stream("GET", url) as response:
                    if response.status_code == 404:
                        raise ExportUnavailable(f"no TMDB export at {url}")
                    response.raise_for_status()
                    for line in _text_lines(response.iter_bytes(_CHUNK_SIZE)):
                        produced += 1
                        yield line
                return
            except _RETRYABLE_STREAM_ERRORS as exc:
                if produced or attempt == _EXPORT_CONNECT_ATTEMPTS:
                    raise
                delay = _EXPORT_RETRY_BACKOFF_S * attempt
                logger.warning(
                    "tmdb export %s %s: %s on attempt %d before any data — retrying in %.0fs",
                    name,
                    day.isoformat(),
                    type(exc).__name__,
                    attempt,
                    delay,
                )
                time.sleep(delay)


def parse_export_line(line: str) -> ExportEntry | None:
    """Parse one JSONL line into an entry, or None if it is unusable.

    A malformed line is skipped rather than raised on: the file has over a
    million of them and one bad row must not cost the whole day's diff.  A row
    with no ``id`` is unusable by definition — the id *is* the payload here.
    """
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except ValueError:
        logger.warning("tmdb export: skipping unparseable line %.80r", line)
        return None
    if not isinstance(raw, dict):
        return None
    external_id = raw.get("id")
    if external_id is None:
        return None
    popularity = raw.get("popularity")
    return ExportEntry(
        external_id=str(external_id),
        # ``original_title`` for movies, ``original_name`` for series — the
        # file uses the same shape as the rest of the API.
        title=str(raw.get("original_title") or raw.get("original_name") or ""),
        popularity=float(popularity) if isinstance(popularity, int | float) else 0.0,
        adult=bool(raw.get("adult")),
        video=bool(raw.get("video")),
    )


def stream_export_entries(name: str, day: date) -> Iterator[ExportEntry]:
    """Parsed entries of one daily export, in file order."""
    for line in stream_export_lines(name, day):
        entry = parse_export_line(line)
        if entry is not None:
            yield entry


def load_export_ids(name: str, day: date) -> set[str]:
    """Every id in one daily export — the *baseline* side of the diff.

    Only the ids are kept.  Holding a million :class:`ExportEntry` objects to
    answer a set-membership question would cost hundreds of megabytes for
    nothing; the fields are only needed for the ids that survive the diff, and
    those come from the other side of it.
    """
    return {entry.external_id for entry in stream_export_entries(name, day)}


def collect_appeared_entries(
    name: str,
    day: date,
    *,
    baseline_ids: set[str],
    known_ids: set[str],
) -> list[ExportEntry]:
    """Entries of ``day``'s export that are new to both TMDB and to us.

    Two subtractions, and both are load-bearing:

    - **against ``baseline_ids``** (the export we last processed) — this is
      what makes the result *new releases* instead of "everything we do not
      have".  Without it the diff would return the entire long tail of items
      that exist at TMDB and were rejected by the ``vote_count`` threshold on
      purpose: hundreds of thousands of rows, none of them a novelty.
    - **against ``known_ids``** (``external_ids`` plus ``seed_targets``) — an
      id already catalogued, already queued for hydration or already retired
      as unreachable is not new work.

    ``adult`` and ``video`` rows are dropped here, mirroring
    ``include_adult=false``/``include_video=false`` in the ``/discover``
    enumeration: the same two kinds of entry the seeded catalog excludes must
    not enter through this door instead.

    Sorted by descending popularity so a truncated or interrupted run has
    spent its requests on the most notable ids rather than on an arbitrary
    slice of the file; the id breaks ties so the order is deterministic.
    """
    appeared: list[ExportEntry] = []
    for entry in stream_export_entries(name, day):
        if entry.external_id in baseline_ids or entry.external_id in known_ids:
            continue
        if entry.adult or entry.video:
            continue
        appeared.append(entry)
    appeared.sort(key=lambda entry: (-entry.popularity, entry.external_id))
    return appeared
