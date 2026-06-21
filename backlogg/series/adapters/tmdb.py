import re
import unicodedata
from datetime import UTC, date, datetime

import httpx

from backlogg.core.config import settings

_TMDB_BASE = "https://api.themoviedb.org/3"
_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


class TMDBSeriesClient:
    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.TMDB_API_KEY}",
            "Accept": "application/json",
        }

    async def search_series(self, query: str) -> dict | None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_TMDB_BASE}/search/tv",
                headers=self._headers,
                params={"query": query},
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            return results[0] if results else None

    async def get_series_detail(self, tmdb_id: int) -> dict | None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_TMDB_BASE}/tv/{tmdb_id}",
                headers=self._headers,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    async def get_series_credits(self, tmdb_id: int) -> dict | None:
        """Return cast and crew dicts for a series, or None on 404."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_TMDB_BASE}/tv/{tmdb_id}/credits",
                headers=self._headers,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    async def get_series_recommendations(self, tmdb_id: int) -> list[dict]:
        """Return page 1 of series recommendations from TMDB, or empty list on 404."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_TMDB_BASE}/tv/{tmdb_id}/recommendations",
                headers=self._headers,
                params={"page": 1},
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    async def get_trending_series(self, period: str = "week") -> list[dict]:
        """Fetch trending TV series from TMDB for the given time window (day or week).

        Returns the first page of results (up to 20 items).
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_TMDB_BASE}/trending/tv/{period}",
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()
        return data.get("results", [])

    async def get_top_series(self, limit: int = 100) -> list[dict]:
        """Fetch popular TV series from TMDB for nightly sync.

        Uses the /tv/popular endpoint and paginates to collect up to
        ``limit`` results (max 500, TMDB returns 20 per page).
        """
        results: list[dict] = []
        page = 1
        while len(results) < limit:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{_TMDB_BASE}/tv/popular",
                    headers=self._headers,
                    params={"page": page},
                )
                response.raise_for_status()
                data = response.json()

            batch = data.get("results", [])
            if not batch:
                break
            results.extend(batch)
            total_pages = data.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1

        return results[:limit]

    def series_to_dict(self, raw: dict) -> dict:
        # TMDB uses "name" for series (not "title")
        title = raw.get("name", "")
        first_air_date_str = raw.get("first_air_date", "")
        last_air_date_str = raw.get("last_air_date", "")

        # Parse first_air_date explicitly
        first_air_date: date | None = None
        year: str = ""
        if first_air_date_str:
            try:
                first_air_date = date.fromisoformat(first_air_date_str)
                year = str(first_air_date.year)
            except ValueError:
                first_air_date = None

        # Parse last_air_date explicitly
        last_air_date: date | None = None
        if last_air_date_str:
            try:
                last_air_date = date.fromisoformat(last_air_date_str)
            except ValueError:
                last_air_date = None

        # Build slug from name and year
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
            "original_title": raw.get("original_name"),
            "slug": slug,
            "overview": raw.get("overview") or None,
            "first_air_date": first_air_date,
            "last_air_date": last_air_date,
            "number_of_seasons": raw.get("number_of_seasons") or None,
            "number_of_episodes": raw.get("number_of_episodes") or None,
            "status": raw.get("status"),
            "original_language": raw.get("original_language"),
            "poster_url": poster_url,
            "backdrop_url": backdrop_url,
            "rating_external": rating_external,
            "rating_count_external": rating_count_external,
            "rating_internal": None,
            "rating_count_internal": 0,
            "last_synced_at": datetime.now(UTC),
            "genres": genres,
        }
