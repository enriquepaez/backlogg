import asyncio
import logging
import re
import unicodedata
from datetime import UTC, date, datetime

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

_OL_BASE = "https://openlibrary.org"
_OL_COVER_BASE = "https://covers.openlibrary.org/b/id"
_OL_HEADERS = {
    "User-Agent": "backlogg/1.0 (https://github.com/enriquepaez/backlogg; contact@backlogg.app)",
}
_OL_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Retry policy for the popular-books search: OL's Solr backend answers the
# readinglog-sorted match-all query with intermittent 500s, and Issue #9
# showed those windows of degradation can last well over the ~30s a short
# retry budget covers (an offset that 500'd through 5 attempts in ~30s
# returned 200 again minutes later, unchanged). 8 attempts with exponential
# backoff (2/4/8/16/30/30/30s, capped at 30s/attempt) give ~120s of total
# retry budget instead.
_SEARCH_RETRY_ATTEMPTS = 8
_OL_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)


def _is_ol_retryable_error(exc: BaseException) -> bool:
    """True for transient Open Library failures: 429/5xx, timeouts and transport errors.

    Never retries a 4xx (e.g. a malformed query or rate-limit block that
    isn't a 429) — retrying would not fix a client error.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _OL_RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.TimeoutException | httpx.TransportError)


_ol_search_retry = retry(
    retry=retry_if_exception(_is_ol_retryable_error),
    stop=stop_after_attempt(_SEARCH_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)

_GENRE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "fiction",
        "nonfiction",
        "non-fiction",
        "science fiction",
        "fantasy",
        "mystery",
        "thriller",
        "horror",
        "romance",
        "historical fiction",
        "biography",
        "autobiography",
        "history",
        "science",
        "philosophy",
        "poetry",
        "drama",
        "adventure",
        "crime",
        "children's",
        "young adult",
        "graphic novel",
        "short stories",
        "essays",
        "self-help",
        "business",
        "technology",
        "travel",
        "cooking",
        "art",
        "music",
        "sports",
        "religion",
        "classics",
        "literary fiction",
        "dystopian",
        "paranormal",
        "suspense",
        "satire",
        "memoir",
        "comics",
    }
)


_CLEAN_SUBJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9'\-]*(?:\s[A-Za-z][A-Za-z0-9'\-]*)?$")


def _is_clean_genre(subject: str) -> bool:
    """Return True if *subject* is suitable as a user-facing genre label.

    A subject is accepted when it is either:
    - present in ``_GENRE_ALLOWLIST`` (case-insensitive), or
    - at most two ASCII words (no parentheses, no comma, ≤ 30 chars).

    Multi-word bibliographic tags like "Lectures et morceaux choisis" or
    long phrases with parentheses/commas are rejected.
    """
    lower = subject.lower().strip()
    if lower in _GENRE_ALLOWLIST:
        return True
    return (
        len(subject) <= 30
        and "(" not in subject
        and ")" not in subject
        and "," not in subject
        and bool(_CLEAN_SUBJECT_RE.match(subject))
    )


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _normalize_edition_as_work(edition: dict) -> dict:
    """Reshape an Open Library edition JSON into work-shaped fields.

    Used by ``get_work_detail`` when the ``work_id`` it was given only
    exists as a standalone edition (``/books/{id}.json``) — confirmed
    against real Open Library responses for the Issue #10 IDs, editions
    never carry ``description`` or ``first_publish_date``/nested-``author``
    ``authors``, so those are reshaped/backfilled here:

    - ``authors``: edition shape is a flat ``[{"key": "/authors/OL..A"}]``;
      work shape (consumed by ``_persist_book_authors``) is
      ``[{"author": {"key": "/authors/OL..A"}}]``.
    - ``first_publish_date``: editions use ``publish_date`` instead; copied
      over only when ``first_publish_date`` is absent, so a genuine work
      value is never overwritten.
    - ``description``: editions don't have one; left absent, which
      ``book_to_dict`` already handles (``overview`` stays ``None``).
    """
    normalized = dict(edition)
    authors = edition.get("authors")
    if authors:
        normalized["authors"] = [
            {"author": {"key": entry["key"]}}
            for entry in authors
            if isinstance(entry, dict) and entry.get("key")
        ]
    if "first_publish_date" not in normalized and normalized.get("publish_date"):
        normalized["first_publish_date"] = normalized["publish_date"]
    return normalized


class OpenLibraryClient:
    async def search_book(self, title: str) -> dict | None:
        """Search Open Library by title and return the first result.

        Not affected by the Issue #10 redirect bug: this hits the
        ``/search.json`` query endpoint (same as ``_fetch_popular_page``),
        not a per-ID detail lookup like ``/works/{id}.json`` or
        ``/authors/{id}.json`` — a search query has no OLID to be the wrong
        record type for, so it never receives the routing-mismatch 301.
        ``follow_redirects`` is deliberately left out.
        """
        async with httpx.AsyncClient(headers=_OL_HEADERS, timeout=_OL_TIMEOUT) as client:
            response = await client.get(
                f"{_OL_BASE}/search.json",
                params={
                    "title": title,
                    "fields": "key,title,author_name,first_publish_year,cover_i,subject,isbn",
                    "limit": 1,
                },
            )
            response.raise_for_status()
            data = response.json()
            docs = data.get("docs", [])
            return docs[0] if docs else None

    @_ol_search_retry
    async def _fetch_popular_page(self, per_page: int, offset: int) -> dict:
        """Fetch one page of the popular-books search, retrying transient failures.

        429/5xx responses, timeouts and transport errors are retried up to
        ``_SEARCH_RETRY_ATTEMPTS`` times with exponential backoff via
        ``tenacity`` (OL's Solr is flaky on this query; a retry after a
        short wait consistently succeeds — see Issue #9 for a case where the
        degradation window outlasted a smaller retry budget). A failure that
        survives every retry — and any other 4xx (e.g. a 403 rate-limit),
        which a retry would not fix — raises ``httpx.HTTPStatusError``:
        callers must never mistake a failed fetch for an exhausted listing.
        """
        params = {
            "q": "*:*",
            "sort": "readinglog",
            "fields": "key,title,author_name,first_publish_year,cover_i,subject,isbn",
            "limit": per_page,
            "offset": offset,
        }
        async with httpx.AsyncClient(headers=_OL_HEADERS, timeout=_OL_TIMEOUT) as client:
            response = await client.get(f"{_OL_BASE}/search.json", params=params)
        response.raise_for_status()
        return response.json()

    async def get_popular_books(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Fetch popular books from Open Library for nightly sync.

        Uses ``GET /search.json`` with a Solr match-all query (``q=*:*``)
        sorted by ``readinglog`` — how many users shelved the work as
        want-to-read/reading/read — which surfaces genuinely popular works
        and supports deep native offset/limit pagination (43M+ works
        indexed), unlike the old ``/trending/weekly.json`` listing that was
        capped at a few hundred entries.

        Returns search docs with the same field set as ``search_book``
        (``key,title,author_name,first_publish_year,cover_i,subject,isbn``),
        which is the shape ``book_to_dict`` consumes.

        Raises ``httpx.HTTPStatusError`` when a page request keeps failing
        after exhausting the retries (or fails with a non-retryable 4xx),
        even mid-pagination: the pages accumulated so far are discarded so a
        returned list always means a fully successful fetch — a 200 response
        with fewer docs than requested is the only legitimate end-of-results
        signal.  Discarding is safe because nothing has been persisted yet,
        upserts are idempotent and the sync cursor is not advanced on error,
        so the next run refetches the same slice.
        """
        results: list[dict] = []
        per_page = min(limit, 100)  # OL search.json default page size

        while len(results) < limit:
            data = await self._fetch_popular_page(per_page, offset)
            docs = data.get("docs", [])
            if not docs:
                logger.info("get_popular_books: no more results at offset %d", offset)
                break
            results.extend(docs)
            if len(docs) < per_page:
                break
            offset += per_page

        return results[:limit]

    async def get_work_detail(self, work_id: str) -> dict | None:
        """Fetch full work detail from Open Library.

        ``work_id`` is the bare OLID like ``OL123W`` (without the /works/ prefix).

        Some ``work_id`` values returned by ``search.json`` are actually
        edition OLIDs (suffix ``M``, not ``W``) that only exist as a
        standalone edition record with no work of their own — Open Library
        answers ``GET /works/{id}.json`` for these with a ``301`` to
        ``GET /books/{id}.json`` (confirmed in production, Issue #10).
        ``follow_redirects=True`` follows it instead of letting
        ``raise_for_status()`` turn the unfollowed redirect into an
        exception. An edition response has a different shape than a work
        response — ``authors`` is a flat ``[{"key": ...}]`` list instead of
        the work's ``[{"author": {"key": ...}}]``, dates live in
        ``publish_date`` instead of ``first_publish_date``, and editions
        carry no ``description`` — so it's normalized into work shape by
        ``_normalize_edition_as_work`` before being returned, so callers
        (``_persist_book_authors``, ``book_to_dict``) don't need to
        special-case it.
        """
        async with httpx.AsyncClient(
            headers=_OL_HEADERS, timeout=_OL_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(f"{_OL_BASE}/works/{work_id}.json")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            detail = response.json()
            if detail.get("type", {}).get("key") == "/type/edition":
                detail = _normalize_edition_as_work(detail)
            return detail

    async def get_author(self, author_id: str) -> dict | None:
        """Fetch author detail from Open Library.

        ``author_id`` is the bare OLID like ``OL123A`` (without the /authors/ prefix).
        Retries up to 3 times on timeout before returning None.

        Follows redirects (``follow_redirects=True``) for consistency with
        ``get_work_detail``: Open Library merges duplicate author records,
        and this client shares the exact same "AsyncClient without
        follow_redirects" pattern that caused Issue #10 for work details.
        No production 301 has been observed here (spot-checked against
        several live author IDs), but the fix is a no-op when unneeded and
        closes the same class of bug defensively.
        """
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    headers=_OL_HEADERS, timeout=_OL_TIMEOUT, follow_redirects=True
                ) as client:
                    response = await client.get(f"{_OL_BASE}/authors/{author_id}.json")
                    if response.status_code == 404:
                        return None
                    response.raise_for_status()
                    return response.json()
            except httpx.TimeoutException:
                if attempt < 2:
                    await asyncio.sleep(1)
                else:
                    logger.warning("get_author: timeout after 3 attempts for %s", author_id)
                    return None
        return None  # unreachable, satisfies type checker

    def book_to_dict(self, search_doc: dict, work_detail: dict | None = None) -> dict:
        """Convert Open Library search doc (+ optional work detail) to a DB-ready dict."""
        title = search_doc.get("title", "")
        first_publish_year = search_doc.get("first_publish_year")

        # Parse first_publish_date — Open Library only gives us a year from search
        first_publish_date: date | None = None
        year_str: str = ""
        if first_publish_year:
            try:
                year = int(first_publish_year)
                first_publish_date = date(year, 1, 1)
                year_str = str(year)
            except (ValueError, TypeError):
                first_publish_date = None

        # If work detail has a more specific date, use it
        if work_detail:
            raw_date = work_detail.get("first_publish_date")
            if raw_date:
                # Try common formats: "2003", "2003-01", "January 2003", "2003-01-15"
                parsed = _parse_ol_date(raw_date)
                if parsed:
                    first_publish_date = parsed
                    year_str = str(parsed.year)

        # Build slug from title and year
        slug_base = _slugify(title)
        slug = f"{slug_base}-{year_str}" if year_str else slug_base

        # Cover image from search result (cover_i is an integer cover ID)
        cover_i = search_doc.get("cover_i")
        poster_url = f"{_OL_COVER_BASE}/{cover_i}-L.jpg" if cover_i else None

        # Synopsis from work detail
        overview: str | None = None
        if work_detail:
            desc = work_detail.get("description")
            if isinstance(desc, str):
                overview = desc or None
            elif isinstance(desc, dict):
                overview = desc.get("value") or None

        # Subjects/genres from search doc — filter to clean, user-facing labels
        subjects = search_doc.get("subject", [])
        genres = []
        seen: set[str] = set()
        for subject in subjects:
            if not _is_clean_genre(subject):
                continue
            genre_slug = _slugify(subject)
            if genre_slug and genre_slug not in seen:
                genres.append({"name": subject, "slug": genre_slug})
                seen.add(genre_slug)
            if len(genres) >= 5:  # cap at 5 genres per book
                break

        # Open Library has no aggregate rating — leave as None
        return {
            "title": title,
            "original_title": None,
            "slug": slug,
            "overview": overview,
            "first_publish_date": first_publish_date,
            "original_language": None,
            "poster_url": poster_url,
            "rating_external": None,
            "rating_count_external": None,
            "rating_internal": None,
            "rating_count_internal": 0,
            "last_synced_at": datetime.now(UTC),
            "genres": genres,
        }


def _parse_ol_date(raw: str) -> date | None:
    """Try to parse Open Library date strings into a Python date.

    Handles formats like "2003", "January 2003", "2003-01-15", "2003-01".
    Returns None when parsing fails.
    """
    raw = raw.strip()

    # ISO date: YYYY-MM-DD
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass

    # Year only: YYYY
    if re.fullmatch(r"\d{4}", raw):
        try:
            return date(int(raw), 1, 1)
        except ValueError:
            pass

    # Year-Month: YYYY-MM
    m = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass

    # "Month YYYY" or "Month Day, YYYY"
    import calendar

    months = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
    month_pattern = "|".join(months)
    m2 = re.search(rf"({month_pattern})\s+(?:\d{{1,2}},\s*)?(\d{{4}})", raw, re.IGNORECASE)
    if m2:
        try:
            month_num = months[m2.group(1).lower()]
            year_num = int(m2.group(2))
            return date(year_num, month_num, 1)
        except (ValueError, KeyError):
            pass

    return None
