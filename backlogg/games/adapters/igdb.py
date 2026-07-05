"""IGDB API client with automatic Twitch OAuth2 token management."""

import re
import time
import unicodedata
from datetime import UTC, date, datetime

import httpx

from backlogg.core.config import settings

_TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_IGDB_BASE = "https://api.igdb.com/v4"

# Map IGDB game_type integer to descriptive string
_GAME_TYPE_MAP: dict[int, str] = {
    0: "MAIN_GAME",
    1: "DLC_ADDON",
    2: "EXPANSION",
    3: "BUNDLE",
    4: "STANDALONE_EXPANSION",
    5: "MOD",
    6: "EPISODE",
    7: "SEASON",
    8: "REMAKE",
    9: "REMASTER",
    10: "EXPANDED_GAME",
    11: "PORT",
    12: "FORK",
    13: "PACK",
    14: "UPDATE",
}


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


class IGDBClient:
    """Client for IGDB API with automatic Twitch token renewal."""

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0  # unix timestamp

    async def _ensure_token(self) -> None:
        """Fetch or renew the Twitch access token if expired or missing."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return  # Token is still valid (60s buffer)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                _TWITCH_TOKEN_URL,
                params={
                    "client_id": settings.TWITCH_CLIENT_ID,
                    "client_secret": settings.TWITCH_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data["access_token"]
            expires_in: int = data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in

    def _headers(self) -> dict[str, str]:
        return {
            "Client-ID": settings.TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {self._access_token}",
        }

    async def _post(self, endpoint: str, body: str) -> list[dict]:
        """POST a query to IGDB and return the JSON list."""
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{_IGDB_BASE}/{endpoint}",
                headers=self._headers(),
                content=body,
            )
            response.raise_for_status()
            return response.json()

    async def get_game_by_slug(self, slug: str) -> dict | None:
        """Fetch a single game from IGDB by slug."""
        query = (
            "fields name,slug,summary,cover.*,first_release_date,rating,rating_count,"
            "game_type,genres.name,genres.slug,platforms.name,platforms.slug,"
            "involved_companies.company.name,involved_companies.company.slug,"
            "involved_companies.developer,involved_companies.publisher;"
            f' where slug = "{slug}";'
            " limit 1;"
        )
        results = await self._post("games", query)
        return results[0] if results else None

    async def search_games(self, query: str, limit: int = 5) -> list[dict]:
        """Search IGDB games by name and return up to ``limit`` results."""
        escaped = query.replace('"', '\\"')
        igdb_query = (
            "fields name,slug,summary,cover.*,first_release_date,rating,rating_count,"
            "game_type,genres.name,genres.slug,platforms.name,platforms.slug,"
            "involved_companies.company.name,involved_companies.company.slug,"
            "involved_companies.developer,involved_companies.publisher;"
            f' search "{escaped}";'
            f" limit {limit};"
        )
        return await self._post("games", igdb_query)

    async def get_top_games(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Fetch top-rated main games from IGDB for seeding.

        ``offset`` maps to IGDB's native ``offset N;`` query clause.
        """
        # IGDB limits to 500 per request; fetch in batches if needed
        per_request = min(limit, 500)
        query = (
            "fields name,slug,summary,cover.*,first_release_date,rating,rating_count,"
            "game_type,genres.name,genres.slug,platforms.name,platforms.slug,"
            "involved_companies.company.name,involved_companies.company.slug,"
            "involved_companies.developer,involved_companies.publisher;"
            " where game_type = (0) & rating > 0;"
            " sort rating_count desc;"
            f" limit {per_request};"
            f" offset {offset};"
        )
        return await self._post("games", query)

    def game_to_dict(self, raw: dict) -> dict:
        """Convert an IGDB game object to a DB-ready dict."""
        title = raw.get("name", "")
        slug = raw.get("slug", _slugify(title))

        # Release date: IGDB gives Unix timestamp (seconds)
        release_date: date | None = None
        ts = raw.get("first_release_date")
        if ts is not None:
            try:
                release_date = datetime.fromtimestamp(int(ts), tz=UTC).date()
            except (ValueError, OSError):
                release_date = None

        # Game type
        game_type_int = raw.get("game_type", 0)
        game_type = _GAME_TYPE_MAP.get(game_type_int, "MAIN_GAME")

        # Cover image
        poster_url: str | None = None
        cover = raw.get("cover")
        if cover and isinstance(cover, dict):
            image_id = cover.get("image_id")
            if image_id:
                poster_url = f"https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg"

        # Rating: IGDB uses 0-100 scale — normalise to 0-10
        rating_raw = raw.get("rating")
        rating_external: float | None = None
        if rating_raw is not None:
            try:
                rating_external = round(float(rating_raw) / 10, 1)
            except (ValueError, TypeError):
                rating_external = None

        rating_count = raw.get("rating_count")

        # Genres
        genres = []
        seen_genres: set[str] = set()
        for g in raw.get("genres") or []:
            if not isinstance(g, dict):
                continue
            g_slug = g.get("slug") or _slugify(g.get("name", ""))
            if g_slug and g_slug not in seen_genres:
                genres.append({"name": g.get("name", g_slug), "slug": g_slug})
                seen_genres.add(g_slug)

        # Platforms
        platforms = []
        seen_platforms: set[str] = set()
        for p in raw.get("platforms") or []:
            if not isinstance(p, dict):
                continue
            p_slug = p.get("slug") or _slugify(p.get("name", ""))
            if p_slug and p_slug not in seen_platforms:
                platforms.append({"name": p.get("name", p_slug), "slug": p_slug})
                seen_platforms.add(p_slug)

        # Companies (developers and publishers)
        companies = []
        seen_company_roles: set[tuple[str, str]] = set()
        for ic in raw.get("involved_companies") or []:
            if not isinstance(ic, dict):
                continue
            company = ic.get("company")
            if not isinstance(company, dict):
                continue
            c_slug = company.get("slug") or _slugify(company.get("name", ""))
            c_name = company.get("name", c_slug)
            if ic.get("developer"):
                key = (c_slug, "DEVELOPER")
                if key not in seen_company_roles:
                    companies.append({"name": c_name, "slug": c_slug, "role": "DEVELOPER"})
                    seen_company_roles.add(key)
            if ic.get("publisher"):
                key = (c_slug, "PUBLISHER")
                if key not in seen_company_roles:
                    companies.append({"name": c_name, "slug": c_slug, "role": "PUBLISHER"})
                    seen_company_roles.add(key)

        return {
            "title": title,
            "original_title": None,
            "slug": slug,
            "overview": raw.get("summary") or None,
            "release_date": release_date,
            "game_type": game_type,
            "original_language": None,
            "poster_url": poster_url,
            "backdrop_url": None,
            "rating_external": rating_external,
            "rating_count_external": rating_count,
            "rating_internal": None,
            "rating_count_internal": 0,
            "last_synced_at": datetime.now(UTC),
            "genres": genres,
            "platforms": platforms,
            "companies": companies,
        }
