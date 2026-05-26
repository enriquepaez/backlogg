import logging
import re
import unicodedata
from datetime import UTC, date, datetime

import httpx

_OL_BASE = "https://openlibrary.org"
_OL_COVER_BASE = "https://covers.openlibrary.org/b/id"
_OL_HEADERS = {
    "User-Agent": "backlogg/1.0 (https://github.com/enriquepaez/backlogg; contact@backlogg.app)",
}

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


class OpenLibraryClient:
    async def search_book(self, title: str) -> dict | None:
        """Search Open Library by title and return the first result."""
        async with httpx.AsyncClient(headers=_OL_HEADERS) as client:
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

    async def get_trending_books(self, limit: int = 100) -> list[dict]:
        """Fetch trending books from Open Library for nightly sync.

        Uses the /trending/weekly.json endpoint which returns top works
        for the current week.  Falls back to an empty list on error.
        """
        results: list[dict] = []
        offset = 0
        per_page = min(limit, 50)  # OL trending endpoint max is typically 50

        while len(results) < limit:
            async with httpx.AsyncClient(headers=_OL_HEADERS) as client:
                response = await client.get(
                    f"{_OL_BASE}/trending/weekly.json",
                    params={"limit": per_page, "offset": offset},
                )
                if response.status_code != 200:
                    logger.warning(
                        "get_trending_books: non-200 status %d at offset %d",
                        response.status_code,
                        offset,
                    )
                    break
                data = response.json()

            works = data.get("works", [])
            if not works:
                break
            results.extend(works)
            if len(works) < per_page:
                break
            offset += per_page

        return results[:limit]

    async def get_work_detail(self, work_id: str) -> dict | None:
        """Fetch full work detail from Open Library.

        ``work_id`` is the bare OLID like ``OL123W`` (without the /works/ prefix).
        """
        async with httpx.AsyncClient(headers=_OL_HEADERS) as client:
            response = await client.get(f"{_OL_BASE}/works/{work_id}.json")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

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

        # Subjects/genres from search doc
        subjects = search_doc.get("subject", [])
        genres = []
        seen: set[str] = set()
        for subject in subjects[:10]:  # cap at 10 genres
            genre_slug = _slugify(subject)
            if genre_slug and genre_slug not in seen:
                genres.append({"name": subject, "slug": genre_slug})
                seen.add(genre_slug)

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
