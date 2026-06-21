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


class TMDBClient:
    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.TMDB_API_KEY}",
            "Accept": "application/json",
        }

    async def search_movie(self, query: str) -> dict | None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_TMDB_BASE}/search/movie",
                headers=self._headers,
                params={"query": query},
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            return results[0] if results else None

    async def get_movie_detail(self, tmdb_id: int) -> dict | None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_TMDB_BASE}/movie/{tmdb_id}",
                headers=self._headers,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    async def get_movie_credits(self, tmdb_id: int) -> dict | None:
        """Return cast and crew dicts for a movie, or None on 404."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_TMDB_BASE}/movie/{tmdb_id}/credits",
                headers=self._headers,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    async def get_movie_recommendations(self, tmdb_id: int) -> list[dict]:
        """Return page 1 of movie recommendations from TMDB, or empty list on 404."""
        async with httpx.AsyncClient() as client:
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

    async def get_trending_movies(self, period: str = "week") -> list[dict]:
        """Fetch trending movies from TMDB for the given time window (day or week).

        Returns the first page of results (up to 20 items).
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_TMDB_BASE}/trending/movie/{period}",
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()
        return data.get("results", [])

    async def get_top_movies(self, limit: int = 100) -> list[dict]:
        """Fetch top-rated movies from TMDB for nightly sync.

        Uses the /movie/popular endpoint and paginates to collect up to
        ``limit`` results (max 500, TMDB returns 20 per page).
        """
        results: list[dict] = []
        page = 1
        while len(results) < limit:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{_TMDB_BASE}/movie/popular",
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
