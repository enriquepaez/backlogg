import re
import unicodedata
from datetime import UTC, date, datetime

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from backlogg.core.config import settings

_TMDB_BASE = "https://api.themoviedb.org/3"
_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
_TMDB_TIMEOUT = 10.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _is_retryable_error(exc: BaseException) -> bool:
    """True for transient TMDB failures: 429/5xx, timeouts and transport errors.

    Never retries 404 (a legitimate "not found") or other 4xx client errors.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.TimeoutException | httpx.TransportError)


_tmdb_retry = retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)


class TMDBClient:
    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.TMDB_API_KEY}",
            "Accept": "application/json",
        }

    @_tmdb_retry
    async def search_movie(self, query: str, year: int | None = None, page: int = 1) -> list[dict]:
        """Search TMDB for movies matching *query* and return the given *page*.

        TMDB's ``/search/movie`` returns ~20 results per page natively via
        the ``page`` param. Returns the full page of results (not just the
        top hit) so callers can ingest more than one match per search.
        """
        params: dict = {"query": query, "page": page}
        if year is not None:
            params["primary_release_year"] = year
        async with httpx.AsyncClient(timeout=_TMDB_TIMEOUT) as client:
            response = await client.get(
                f"{_TMDB_BASE}/search/movie",
                headers=self._headers,
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    @_tmdb_retry
    async def get_movie_detail(self, tmdb_id: int) -> dict | None:
        async with httpx.AsyncClient(timeout=_TMDB_TIMEOUT) as client:
            response = await client.get(
                f"{_TMDB_BASE}/movie/{tmdb_id}",
                headers=self._headers,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    @_tmdb_retry
    async def get_movie_credits(self, tmdb_id: int) -> dict | None:
        """Return cast and crew dicts for a movie, or None on 404."""
        async with httpx.AsyncClient(timeout=_TMDB_TIMEOUT) as client:
            response = await client.get(
                f"{_TMDB_BASE}/movie/{tmdb_id}/credits",
                headers=self._headers,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    @_tmdb_retry
    async def get_movie_recommendations(self, tmdb_id: int) -> list[dict]:
        """Return page 1 of movie recommendations from TMDB, or empty list on 404."""
        async with httpx.AsyncClient(timeout=_TMDB_TIMEOUT) as client:
            response = await client.get(
                f"{_TMDB_BASE}/movie/{tmdb_id}/recommendations",
                headers=self._headers,
                params={"page": 1},
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    @_tmdb_retry
    async def get_trending_movies(self, period: str = "week") -> list[dict]:
        """Fetch trending movies from TMDB for the given time window (day or week).

        Returns the first page of results (up to 20 items).
        """
        async with httpx.AsyncClient(timeout=_TMDB_TIMEOUT) as client:
            response = await client.get(
                f"{_TMDB_BASE}/trending/movie/{period}",
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()
        return data.get("results", [])

    @_tmdb_retry
    async def _get_popular_page(self, page: int) -> dict:
        """Fetch a single page of /movie/popular. Retried as a unit per page."""
        async with httpx.AsyncClient(timeout=_TMDB_TIMEOUT) as client:
            response = await client.get(
                f"{_TMDB_BASE}/movie/popular",
                headers=self._headers,
                params={"page": page},
            )
            response.raise_for_status()
            return response.json()

    async def get_top_movies(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Fetch top-rated movies from TMDB for nightly sync.

        Uses the /movie/popular endpoint and paginates to collect up to
        ``limit`` results starting at ``offset`` (TMDB returns 20 per page,
        so the offset is translated to a page number and the leading
        ``offset % 20`` items of the first page are discarded).

        TMDB caps pagination at page 500 — requests beyond it return an
        empty list.
        """
        results: list[dict] = []
        page = offset // 20 + 1
        skip = offset % 20
        while len(results) < limit:
            if page > 500:
                break
            data = await self._get_popular_page(page)

            batch = data.get("results", [])
            if not batch:
                break
            if skip:
                batch = batch[skip:]
                skip = 0
            results.extend(batch)
            total_pages = data.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1

        return results[:limit]

    def movie_to_dict(self, raw: dict) -> dict:
        title = raw.get("title", "")
        release_date_str = raw.get("release_date", "")

        # Parse release_date explicitly
        release_date: date | None = None
        year: str = ""
        if release_date_str:
            try:
                release_date = date.fromisoformat(release_date_str)
                year = str(release_date.year)
            except ValueError:
                release_date = None

        # Build slug from title and year
        slug_base = _slugify(title)
        slug = f"{slug_base}-{year}" if year else slug_base

        # Build image URLs
        poster_path = raw.get("poster_path")
        backdrop_path = raw.get("backdrop_path")
        poster_url = f"{_TMDB_IMAGE_BASE}{poster_path}" if poster_path else None
        backdrop_url = f"{_TMDB_IMAGE_BASE}{backdrop_path}" if backdrop_path else None

        # Process genres from detail response (list of {id, name})
        genres = []
        for g in raw.get("genres", []):
            name = g["name"]
            genres.append({"name": name, "slug": _slugify(name)})

        # Rating — TMDB uses vote_average (0–10), Numeric(3,1) stores 1 decimal
        vote_average = raw.get("vote_average")
        rating_external = round(float(vote_average), 1) if vote_average else None
        vote_count = raw.get("vote_count")
        rating_count_external = int(vote_count) if vote_count else None

        return {
            "title": title,
            "original_title": raw.get("original_title"),
            "slug": slug,
            "overview": raw.get("overview") or None,
            "release_date": release_date,
            "runtime": raw.get("runtime") or None,
            "original_language": raw.get("original_language"),
            "poster_url": poster_url,
            "backdrop_url": backdrop_url,
            "budget": raw.get("budget") or None,
            "revenue": raw.get("revenue") or None,
            "status": raw.get("status"),
            "rating_external": rating_external,
            "rating_count_external": rating_count_external,
            "rating_internal": None,
            "rating_count_internal": 0,
            "last_synced_at": datetime.now(UTC),
            "genres": genres,
        }
