"""Seed the book catalog from Open Library's monthly dumps (feature 87).

Why this exists
---------------
Until this module the book catalog was *enumerated* through ``search.json``:
one Solr query per page of the seed, plus one ``/works/{id}.json`` and one
``/authors/{id}.json`` per item to get authorship.  That path is the source of
the intermittent 500s of issue #9 (and of the ~120 s retry budget the adapter
now carries), and it is also exactly what Open Library's own API policy asks
callers **not** to do — "do not harvest data in bulk", "do not make hundreds of
single-book requests", 1 req/s unidentified (see ``docs/external-apis.md``).

Open Library publishes the whole database as monthly dumps.  Seeding from them
replaces tens of thousands of HTTP requests with four sequential downloads and
**zero** per-item requests.

What this module does *not* change
----------------------------------
The nightly job (``backlogg.scheduler.jobs.sync_books``), ``search_book``, the
on-demand fallback and ``get_book`` still go through ``search.json``.  This is
the **seeding** path, not the request path.  The dump-based *incremental* is
feature 88 (``docs/seeding-plan.md`` §6).

The four passes, and why in this order
--------------------------------------
::

    1. reading-log (0,12 GB) -> COUNT(*) per work -> whitelist (>= 5 shelvings)
    2. editions   (12,59 GB) -> aggregate ONLY whitelisted works, then apply the
                                feature-73 filter -> the selected catalog
    3. works      (4,06 GB)  -> title/subjects/covers/description/author keys of
                                the selected works only
    4. authors    (0,78 GB)  -> names of the author keys collected in pass 3

The order is what makes a 17,5 GB corpus fit in bounded memory.  Almost every
selection field lives in the **editions**, not in the work: ``edition_count``,
``number_of_pages_median``, ``language`` (a work has no language at all),
``first_publish_year``, ``ddc``, ``lcc`` and ``isbn`` are all aggregated from
editions — which is precisely what Solr does to build a ``search.json`` doc.
Without pass 1 first, pass 2 would need a map keyed by all 41,6 M works; with
it, the map is keyed by the 399.259 works that reach 5 shelvings (measured on
the 2026-08-31 dump), and passes 3-4 are keyed by the ~19 k selected ones.

Nothing is written to disk from the dumps themselves: every pass is
``httpx.stream`` + ``gzip`` over the socket.  What lands on disk is the small
artifact each pass leaves in the work dir, which is what makes the pipeline
resumable per phase (see ``scripts/seed_openlibrary_books.py``).

Dump format (verified against the real bytes, 2026-09-04)
---------------------------------------------------------
``works``/``editions``/``authors`` are 5-column TSV with **no header**::

    type \t key \t revision \t last_modified \t JSON

The JSON column is escaped (``\\uXXXX``), so it can never contain a raw tab or
newline: ``line.split("\\t", 4)`` is safe.  ``reading-log`` is a **different**,
4-column format with no JSON at all::

    work_key \t edition_key \t shelf \t date

with ``\\N`` for a missing edition and four possible shelves ("Want to Read",
"Already Read", "Currently Reading", "Stopped Reading").  ``readinglog_count``
is ``COUNT(*)`` over all four, unweighted — contrasted against Solr, exact on
the works that sit on the threshold.

Classification is not reimplemented here
----------------------------------------
``build_search_doc`` assembles a dict with the same shape ``search.json``
returns, and the caller feeds it to ``OpenLibraryClient.book_to_dict``.  Genres
(feature 72), the slug and its issue-#18 fallback, and the dict shape therefore
come from the *same* code the on-demand path uses.  The raw dump notations
(``"303.48/33"``, ``"T14.5 .L58 1997"``) go through the existing parsers
unchanged; ``tests/books/test_openlibrary_dump_fixture.py`` proves on real dump
lines that the genres derived this way match the ones derived from
``search.json`` for the same works.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import math
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Iterable, Iterator
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import IO, Any

import httpx

from backlogg.books.constants import BOOK_LANGUAGE_EN, BOOK_LANGUAGE_ES
from backlogg.core.config import settings
from backlogg.shared.bulk_load import BulkPerson
from backlogg.shared.slugs import slug_with_external_fallback

logger = logging.getLogger(__name__)

_DUMP_URL = "https://openlibrary.org/data/ol_dump_{name}_latest.txt.gz"

DUMP_READING_LOG = "reading-log"
DUMP_EDITIONS = "editions"
DUMP_WORKS = "works"
DUMP_AUTHORS = "authors"

# openlibrary.org redirects to archive.org, which redirects again to the
# node holding the item, so redirects must be followed.  The read timeout is
# generous on purpose: these are multi-GB responses over a link measured at
# ~6 MB/s, and a stall mid-stream cannot be resumed (gzip has no seek point),
# so it is better to wait than to have to redo a 35-minute pass.
_DUMP_TIMEOUT = httpx.Timeout(120.0, connect=30.0)
_DUMP_HEADERS = {
    "User-Agent": "backlogg/1.0 (https://github.com/enriquepaez/backlogg; contact@backlogg.app)",
}
_CHUNK_SIZE = 1 << 20

# Attempts to *open* a dump stream. See ``stream_dump_lines``: this budget
# applies only while no line has been handed out yet.
_DUMP_CONNECT_ATTEMPTS = 3
_DUMP_RETRY_BACKOFF_S = 5.0

# What counts as "the download failed" rather than "the dump is wrong".
# ``EOFError``/``BadGzipFile`` are in here on purpose: a body that ends early
# is a cut connection seen from one layer up, and before this it behaved
# differently from an ``httpx.ReadError`` **by accident** — it escaped the
# except clause entirely — rather than by decision. Now one rule governs all
# of them, and it is the asymmetry in ``stream_dump_lines``: retry only while
# nothing has been handed out.
_RETRYABLE_STREAM_ERRORS = (
    httpx.TransportError,
    httpx.HTTPStatusError,
    EOFError,
    gzip.BadGzipFile,
)

# A four-digit year inside an edition's free-text ``publish_date``.  The field
# is genuinely free text: the fixture alone carries "2005", "2005-03-17",
# "February 27, 1997", "Dec 04, 2018", "nov 15 2018", "4/12/2018",
# "28 septembre 2023" and "Octubre 2021", and the corpus adds the library
# conventions "c1985" (circa), "[1985]" (supplied by the cataloguer) and
# "1985?" (uncertain).  All of those name the same thing — the year — so all of
# them are accepted.
#
# The guard is on digits, not on word boundaries: ``\b`` would reject "c1985"
# (``c`` and ``1`` are both word characters, so there is no boundary between
# them) while still accepting every other form, which is exactly the kind of
# silent, partial correctness worth avoiding.  ``(?<!\d)``/``(?!\d)`` instead
# rejects only what must be rejected: a run of digits longer than four, i.e.
# ISBNs, LCCNs and OCLC numbers that happen to contain "1997".
_YEAR_RE = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")

# Work keys as they appear inside an edition's raw JSON ("/works/OL1234W").
# Used only as a pre-filter over the raw line — see ``aggregate_editions``.
_WORK_KEY_RE = re.compile(r"/works/(OL\d+W)")

__all__ = [
    "DUMP_AUTHORS",
    "DUMP_EDITIONS",
    "DUMP_READING_LOG",
    "DUMP_WORKS",
    "EditionAggregate",
    "SelectedWork",
    "WorkRecord",
    "aggregate_editions",
    "author_rows",
    "build_search_doc",
    "build_work_detail",
    "collect_author_names",
    "collect_work_records",
    "count_reading_log",
    "dump_url",
    "merge_edition",
    "parse_dump_line",
    "parse_reading_log_line",
    "parse_work_record",
    "select_language",
    "select_works",
    "split_dump_line",
    "stream_dump_lines",
    "whitelist_threshold",
]


# ── Streaming ────────────────────────────────────────────────────────────────


def dump_url(name: str) -> str:
    """URL of the ``latest`` monthly dump *name* (redirects to archive.org)."""
    return _DUMP_URL.format(name=name)


class _ChunkReader(io.RawIOBase):
    """Minimal file-like view over an ``httpx`` byte iterator.

    ``gzip.GzipFile`` needs an object with ``read(n)``; ``httpx`` gives an
    iterator of chunks.  Wrapping instead of buffering the whole body is the
    entire point: the response is 12,59 GB.  Handing the job to ``GzipFile``
    (rather than driving ``zlib`` by hand) also means multi-member gzip files
    keep working for free.
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


def stream_dump_lines(name: str) -> Iterator[str]:
    """Stream one dump line by line, decompressing on the fly.

    Not a coroutine on purpose: the four passes are CPU/network bound and do
    no database work, so the seeding script runs them synchronously and only
    enters an event loop for the final write phase.

    Retries **only before the first line is yielded**, and that asymmetry is
    the whole point.  A failure while opening the stream costs nothing to
    redo; a failure mid-stream cannot be resumed at all (gzip has no seek
    point) and re-reading from the top would feed the caller the same
    millions of lines twice, so it is raised and the phase is re-run — which
    is cheap, because the phases before it kept their artifacts.

    Not hypothetical, in either direction: a measured full run on 2026-09-04
    lost the works pass four seconds in to ``ConnectError: [Errno 104]
    Connection reset by peer`` from archive.org (retried, free), right after
    two hours of downloading editions (where a retry would have re-emitted
    millions of lines and inflated every aggregate built from them).
    """
    url = dump_url(name)
    with httpx.Client(
        headers=_DUMP_HEADERS, timeout=_DUMP_TIMEOUT, follow_redirects=True
    ) as client:
        for attempt in range(1, _DUMP_CONNECT_ATTEMPTS + 1):
            produced = 0
            try:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    for line in _text_lines(response.iter_bytes(_CHUNK_SIZE)):
                        produced += 1
                        yield line
                return
            except _RETRYABLE_STREAM_ERRORS as exc:
                if produced or attempt == _DUMP_CONNECT_ATTEMPTS:
                    raise
                delay = _DUMP_RETRY_BACKOFF_S * attempt
                logger.warning(
                    "dump %s: %s on attempt %d before any data — retrying in %.0fs",
                    name,
                    type(exc).__name__,
                    attempt,
                    delay,
                )
                time.sleep(delay)


# ── Parsing ──────────────────────────────────────────────────────────────────


def split_dump_line(line: str) -> tuple[str, str, str] | None:
    """Split one dump line into ``(type, key, raw_json)`` without parsing the JSON.

    Separate from ``parse_dump_line`` because ``json.loads`` is by far the most
    expensive thing these passes do (41,6 M work records, 56,7 M edition ones,
    measured on the 2026-08-31 dump) and the
    passes that filter by key can decide to skip a record *before* paying for
    it.  The split itself is safe on 5 columns: the JSON column is escaped
    (``\\uXXXX``), so it can never contain a raw tab.
    """
    if not line:
        return None
    parts = line.split("\t", 4)
    if len(parts) < 5:
        return None
    return parts[0], parts[1], parts[4]


def parse_dump_line(line: str) -> tuple[str, str, dict] | None:
    """Parse one 5-column dump line into ``(type, key, record)``.

    Returns ``None`` for a line that is empty, short of columns or carries
    unparseable JSON: a dump is 17,5 GB of third-party data and one bad line
    must never abort a 35-minute pass.
    """
    split = split_dump_line(line)
    if split is None:
        return None
    record = _load_record(split[2])
    if record is None:
        return None
    return split[0], split[1], record


def _load_record(raw: str) -> dict | None:
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def parse_reading_log_line(line: str) -> str | None:
    """Work id of one reading-log row, or ``None`` if the row is unusable.

    The reading-log dump does **not** share the 5-column shape of the others:
    it is ``work_key \\t edition_key \\t shelf \\t date`` with no JSON.
    """
    if not line:
        return None
    work_key, _, rest = line.partition("\t")
    if not rest or not work_key.startswith("/works/"):
        return None
    return work_key.removeprefix("/works/")


def _as_set(values: Iterable[str]) -> AbstractSet[str]:
    """Membership-testable view of *values*, without copying when avoidable.

    ``dict.keys()`` is already a ``Set`` with O(1) membership, and the
    whitelist handed to the editions pass is exactly that — 399 k keys. Copying
    it into a new ``set`` would add tens of MB to the peak of the heaviest pass
    for nothing.
    """
    return values if isinstance(values, AbstractSet) else set(values)


def _key_id(value: object, prefix: str) -> str | None:
    """``"/works/OL1W"`` -> ``"OL1W"``. ``None`` for anything else."""
    if not isinstance(value, str) or not value.startswith(prefix):
        return None
    return value.removeprefix(prefix) or None


# ── Pass 1: reading-log -> whitelist ─────────────────────────────────────────


def whitelist_threshold() -> int:
    """Shelvings a work needs to be worth aggregating its editions for.

    The **lower** of the two feature-73 thresholds: a work under it cannot
    qualify through either stream, so pass 2 can forget it and keep its map
    at 399.259 keys instead of 41,6 M.
    """
    return min(settings.BOOKS_SEED_MIN_READINGLOG, settings.BOOKS_SEED_MIN_READINGLOG_ES)


def count_reading_log(lines: Iterable[str], *, min_count: int | None = None) -> dict[str, int]:
    """``readinglog_count`` per work, keeping only works at or above the floor.

    ``COUNT(*)`` over the four shelves, unweighted — the same number Solr
    exposes as ``readinglog_count`` (contrasted against live Solr on works
    sitting exactly on the threshold: identical).

    The intermediate ``Counter`` is over all ~3,3 M shelved works, which is
    the honest peak of this pass — **444 MB of RSS, measured** on the
    2026-08-31 dump — and the returned dict is pruned to the 399.259 works
    that reach the floor.  (The heavier pass that follows peaks at 574 MB with
    that whitelist in hand; see ``docs/operations.md``.)
    """
    floor = whitelist_threshold() if min_count is None else min_count
    counts: Counter[str] = Counter()
    for line in lines:
        work_id = parse_reading_log_line(line)
        if work_id is not None:
            counts[work_id] += 1
    return {work_id: count for work_id, count in counts.items() if count >= floor}


# ── Pass 2: editions -> per-work aggregate ───────────────────────────────────


@dataclass(slots=True)
class EditionAggregate:
    """The fields Solr computes from a work's editions, computed here instead.

    Every one of them is an aggregate over editions because that is where the
    data lives — a work record carries no language, no page count, no ISBN and
    no classification.
    """

    edition_count: int = 0
    languages: set[str] = field(default_factory=set)
    pages: list[int] = field(default_factory=list)
    ddc: list[str] = field(default_factory=list)
    lcc: list[str] = field(default_factory=list)
    isbn: str | None = None
    first_publish_year: int | None = None
    cover_id: int | None = None

    @property
    def pages_median(self) -> int | None:
        """Median page count over the editions that declare one.

        ``ceil``, not ``int``: that is literally what Open Library does
        (``number_of_pages_median`` in ``openlibrary/solr/updater/work.py`` is
        ``ceil(median(number_of_pages))``).  The two only differ when the
        median lands on a half — an even number of editions with page counts —
        and none of the fixture works happens to hit that case, so this one
        line is settled by reading the upstream source rather than by the
        comparison test.  Rounding the other way would move a work by one page
        against ``BOOKS_SEED_MIN_PAGES``.

        Editions with no page count do not vote; an explicit ``0`` does, again
        because upstream only skips ``None``.
        """
        if not self.pages:
            return None
        return math.ceil(statistics.median(self.pages))

    def to_json(self) -> dict:
        return {
            "edition_count": self.edition_count,
            "languages": sorted(self.languages),
            "pages_median": self.pages_median,
            "ddc": self.ddc,
            "lcc": self.lcc,
            "isbn": self.isbn,
            "first_publish_year": self.first_publish_year,
            "cover_id": self.cover_id,
        }


def _publish_year(raw: object) -> int | None:
    """First plausible four-digit year inside an edition's ``publish_date``."""
    if not isinstance(raw, str):
        return None
    match = _YEAR_RE.search(raw)
    return int(match.group(1)) if match else None


def _edition_isbn(record: dict) -> str | None:
    """First ISBN of an edition, 13 preferred over 10."""
    for key in ("isbn_13", "isbn_10"):
        values = record.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _first_cover(record: dict) -> int | None:
    """First usable cover id. Open Library writes ``-1`` for "no cover"."""
    covers = record.get("covers")
    if not isinstance(covers, list):
        return None
    for cover in covers:
        if isinstance(cover, int) and cover > 0:
            return cover
    return None


def _str_values(record: dict, key: str, *, intern: bool = False) -> list[str]:
    """Non-empty string values of a list field, optionally interned.

    Interning is applied **per field, on measured repetition**, not as a blanket
    habit — since CPython 3.12 interned strings are immortal, so interning a
    near-unique value raises the memory floor instead of lowering the peak.
    Measured over the 19.221 selected works of the 2026-08-31 dump:

    ==============  =======  ========  =====================================
    Field           values   distinct  verdict
    ==============  =======  ========  =====================================
    ``languages``    59.482       216  intern (repeat ratio 275x)
    ``ddc``         115.934    10.717  intern (10,8x)
    ``lcc``         214.667   164.767  **do not** intern (1,3x — a call number
                                       carries the author/date signature, so
                                       it is almost a unique string)
    ==============  =======  ========  =====================================
    """
    values = record.get(key)
    if not isinstance(values, list):
        return []
    clean = [value for value in values if isinstance(value, str) and value]
    return [sys.intern(value) for value in clean] if intern else clean


def _edition_languages(record: dict) -> list[str]:
    languages = record.get("languages")
    if not isinstance(languages, list):
        return []
    codes = []
    for entry in languages:
        if isinstance(entry, dict):
            code = _key_id(entry.get("key"), "/languages/")
            if code:
                codes.append(sys.intern(code))
    return codes


def _edition_work_ids(record: dict) -> list[str]:
    works = record.get("works")
    if not isinstance(works, list):
        return []
    ids = []
    for entry in works:
        if isinstance(entry, dict):
            work_id = _key_id(entry.get("key"), "/works/")
            if work_id:
                ids.append(work_id)
    return ids


def merge_edition(aggregate: EditionAggregate, record: dict) -> None:
    """Fold one edition record into its work's aggregate."""
    aggregate.edition_count += 1
    aggregate.languages.update(_edition_languages(record))
    pages = record.get("number_of_pages")
    if isinstance(pages, int) and not isinstance(pages, bool) and pages >= 0:
        aggregate.pages.append(pages)
    aggregate.ddc.extend(_str_values(record, "dewey_decimal_class", intern=True))
    aggregate.lcc.extend(_str_values(record, "lc_classifications"))
    if aggregate.isbn is None:
        aggregate.isbn = _edition_isbn(record)
    year = _publish_year(record.get("publish_date"))
    if year is not None and (
        aggregate.first_publish_year is None or year < aggregate.first_publish_year
    ):
        aggregate.first_publish_year = year
    if aggregate.cover_id is None:
        aggregate.cover_id = _first_cover(record)


def aggregate_editions(
    lines: Iterable[str], whitelist: Iterable[str]
) -> dict[str, EditionAggregate]:
    """Aggregate the editions of the whitelisted works, ignoring every other one.

    The whitelist is the load-bearing part: an edition whose ``works[]`` points
    outside it is dropped without allocating anything, which is what keeps the
    12,59 GB pass proportional to the shelved catalog (399 k works) and not to
    the corpus (56,7 M editions / 41,6 M works, measured).
    """
    wanted = _as_set(whitelist)
    aggregates: dict[str, EditionAggregate] = {}
    for line in lines:
        split = split_dump_line(line)
        if split is None:
            continue
        # Cheap pre-filter before the expensive part. Most of the 56,7 M
        # editions belong to works nobody has shelved five times, and finding
        # the work key with a regex over the raw line costs a fraction of
        # ``json.loads``. It is only a filter: the authoritative list still
        # comes from the parsed record below, so a false positive costs
        # nothing and a work key appearing somewhere odd changes no outcome.
        if not any(work_id in wanted for work_id in _WORK_KEY_RE.findall(split[2])):
            continue
        record = _load_record(split[2])
        if record is None:
            continue
        for work_id in _edition_work_ids(record):
            if work_id not in wanted:
                continue
            aggregate = aggregates.get(work_id)
            if aggregate is None:
                aggregate = EditionAggregate()
                aggregates[work_id] = aggregate
            merge_edition(aggregate, record)
    return aggregates


# ── Selection: the feature-73 filter, reproduced ─────────────────────────────


@dataclass(frozen=True, slots=True)
class SelectedWork:
    """A work that clears the feature-73 filter, and the stream it clears it in."""

    work_id: str
    language: str
    readinglog_count: int
    aggregate: EditionAggregate


def _clears(
    *, readinglog: int, editions: int, pages: int | None, min_readinglog: int, min_editions: int
) -> bool:
    return (
        readinglog >= min_readinglog
        and editions >= min_editions
        and pages is not None
        and pages >= settings.BOOKS_SEED_MIN_PAGES
    )


def select_language(readinglog_count: int, aggregate: EditionAggregate) -> str | None:
    """Which seed stream a work belongs to, or ``None`` if it belongs to neither.

    This is ``build_seed_query`` (``backlogg/books/adapters/open_library.py``)
    expressed over locally computed aggregates instead of over Solr:

    * English — ``language:eng AND readinglog_count:[20 TO *] AND
      edition_count:[10 TO *] AND number_of_pages_median:[100 TO *]``
    * Spanish — ``language:spa AND NOT language:eng`` with the lower
      ``readinglog_count:[5 TO *]`` / ``edition_count:[2 TO *]`` thresholds,
      because the shelving signal is ~10x weaker in Spanish.

    The ``NOT language:eng`` half is not cosmetic: ``language`` is multivalued
    at work level (the union of the editions' languages), so without it the
    Spanish stream would return the English list.  Thresholds are read from
    ``settings`` at call time so an env override or a test monkeypatch applies
    without reimporting.
    """
    languages = aggregate.languages
    pages = aggregate.pages_median
    if BOOK_LANGUAGE_EN in languages:
        if _clears(
            readinglog=readinglog_count,
            editions=aggregate.edition_count,
            pages=pages,
            min_readinglog=settings.BOOKS_SEED_MIN_READINGLOG,
            min_editions=settings.BOOKS_SEED_MIN_EDITIONS,
        ):
            return BOOK_LANGUAGE_EN
        return None
    if BOOK_LANGUAGE_ES in languages:
        if _clears(
            readinglog=readinglog_count,
            editions=aggregate.edition_count,
            pages=pages,
            min_readinglog=settings.BOOKS_SEED_MIN_READINGLOG_ES,
            min_editions=settings.BOOKS_SEED_MIN_EDITIONS_ES,
        ):
            return BOOK_LANGUAGE_ES
        return None
    return None


def select_works(
    readinglog_counts: dict[str, int], aggregates: dict[str, EditionAggregate]
) -> list[SelectedWork]:
    """Apply ``select_language`` to every aggregated work, in work-id order."""
    selected = []
    for work_id in sorted(aggregates):
        aggregate = aggregates[work_id]
        count = readinglog_counts.get(work_id, 0)
        language = select_language(count, aggregate)
        if language is not None:
            selected.append(SelectedWork(work_id, language, count, aggregate))
    return selected


# ── Pass 3: works -> title, subjects, covers, description, author keys ───────


@dataclass(frozen=True, slots=True)
class WorkRecord:
    """The work-level half of a book: everything the editions cannot give."""

    work_id: str
    title: str
    subjects: list[str]
    cover_id: int | None
    description: str | None
    author_ids: list[str]

    def to_json(self) -> dict:
        return {
            "work_id": self.work_id,
            "title": self.title,
            "subjects": self.subjects,
            "cover_id": self.cover_id,
            "description": self.description,
            "author_ids": self.author_ids,
        }


def _description(record: dict) -> str | None:
    """Open Library writes a description either as a string or as a typed dict."""
    value = record.get("description")
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        text = value.get("value")
        return text or None
    return None


def _work_author_ids(record: dict) -> list[str]:
    """Author OLIDs of a work record, order preserved and de-duplicated."""
    authors = record.get("authors")
    if not isinstance(authors, list):
        return []
    ids: list[str] = []
    for entry in authors:
        if not isinstance(entry, dict):
            continue
        author = entry.get("author")
        key = author.get("key") if isinstance(author, dict) else entry.get("key")
        author_id = _key_id(key, "/authors/")
        if author_id and author_id not in ids:
            ids.append(author_id)
    return ids


def parse_work_record(work_id: str, record: dict) -> WorkRecord:
    """Map one work JSON onto the fields the catalog row needs."""
    title = record.get("title")
    return WorkRecord(
        work_id=work_id,
        title=title if isinstance(title, str) else "",
        subjects=[value for value in _str_values(record, "subjects")],
        cover_id=_first_cover(record),
        description=_description(record),
        author_ids=_work_author_ids(record),
    )


def collect_work_records(lines: Iterable[str], wanted: Iterable[str]) -> dict[str, WorkRecord]:
    """Pull the work records of the selected works out of the works dump."""
    keys = _as_set(wanted)
    records: dict[str, WorkRecord] = {}
    for line in lines:
        split = split_dump_line(line)
        if split is None:
            continue
        # Key column first, JSON only for the ~19 k works that matter: this
        # pass sees 41,6 M lines and parsing all of them would dominate it.
        work_id = _key_id(split[1], "/works/")
        if work_id is None or work_id not in keys:
            continue
        record = _load_record(split[2])
        if record is None:
            continue
        records[work_id] = parse_work_record(work_id, record)
    return records


# ── Pass 4: authors -> names ─────────────────────────────────────────────────


def collect_author_names(lines: Iterable[str], wanted: Iterable[str]) -> dict[str, str]:
    """Names of the wanted author OLIDs. ``personal_name`` backs up ``name``.

    An author key that never shows up in the dump simply has no entry: the
    book is still seeded, just with one credit fewer — the same graceful
    degradation ``collect_book_authors`` has always had for a failed
    ``/authors/{id}`` call.
    """
    keys = _as_set(wanted)
    names: dict[str, str] = {}
    for line in lines:
        split = split_dump_line(line)
        if split is None:
            continue
        author_id = _key_id(split[1], "/authors/")
        if author_id is None or author_id not in keys:
            continue
        record = _load_record(split[2])
        if record is None:
            continue
        name = record.get("name") or record.get("personal_name")
        if isinstance(name, str) and name.strip():
            names[author_id] = name.strip()
    return names


def author_rows(author_ids: Iterable[str], names: dict[str, str]) -> list[BulkPerson]:
    """Map author OLIDs + names onto ``BulkPerson`` rows with role ``AUTHOR``.

    Same contract as ``backlogg.books.service.collect_book_authors`` — which
    is deliberately left untouched — minus its one HTTP request per author:
    the name already came down with the authors dump.
    """
    rows: list[BulkPerson] = []
    for author_id in author_ids:
        name = names.get(author_id)
        if not name:
            continue
        rows.append(
            BulkPerson(
                source="OPEN_LIBRARY",
                external_id=author_id,
                name=name,
                # Issue #18: a non-Latin name folds to "" and would collapse
                # every such author onto one row through uq_people_slug.
                slug=slug_with_external_fallback(name, "OPEN_LIBRARY", author_id),
                profile_url=None,
                role="AUTHOR",
            )
        )
    return rows


# ── The search-doc bridge ────────────────────────────────────────────────────


def build_search_doc(selected: SelectedWork, work: WorkRecord) -> dict:
    """Assemble the ``search.json``-shaped doc ``book_to_dict`` consumes.

    Deliberately the *same* shape ``_OL_SEARCH_FIELDS`` declares, so the dump
    path and the request path share one mapper instead of two that drift
    (which is what issue #17 was).  Field by field:

    * ``key``/``title`` — from the work record.
    * ``first_publish_year`` — ``min`` of the editions' publish years, which is
      how Solr computes it.  The work's own ``first_publish_date`` is
      deliberately *not* used even when present (2,6 % of records): Solr
      ignores it, and reading it here would move the year, and with it the
      slug, away from the value already persisted for books seeded through
      ``search.json``.
    * ``cover_i`` — the work's cover, falling back to the first edition cover.
    * ``isbn``/``ddc``/``lcc`` — aggregated from the editions.  ``book_to_dict``
      takes ``isbn[0]``, so only the first one is carried.
    * ``subject_facet`` — the work's ``subjects``.  Solr derives its
      ``subject_facet`` from exactly this field, and ``_derive_genres`` only
      ever matches it against a closed vocabulary, so an unnormalized value
      cannot leak into ``book_genres``.
    """
    aggregate = selected.aggregate
    return {
        "key": f"/works/{selected.work_id}",
        "title": work.title,
        "first_publish_year": aggregate.first_publish_year,
        "cover_i": work.cover_id if work.cover_id is not None else aggregate.cover_id,
        "isbn": [aggregate.isbn] if aggregate.isbn else [],
        "ddc": aggregate.ddc,
        "lcc": aggregate.lcc,
        "subject_facet": work.subjects,
    }


def build_work_detail(work: WorkRecord) -> dict | None:
    """The optional second argument of ``book_to_dict``: description only.

    ``first_publish_date`` is intentionally left out — see ``build_search_doc``.
    """
    if work.description is None:
        return None
    return {"description": work.description}
