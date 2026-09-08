"""IGDB API client with automatic Twitch OAuth2 token management."""

import asyncio
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from backlogg.core.config import settings
from backlogg.games.constants import ALLOWED_GAME_CATEGORY_IDS, GAME_TYPE_MAP
from backlogg.shared.slugs import external_id_slug, slugify

_TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_IGDB_BASE = "https://api.igdb.com/v4"

# Delay between paginated requests — IGDB allows at most 4 req/s.  Public
# because the catalog enumeration of feature 90 owns its own page loop (it
# lives in ``backlogg.scheduler.igdb_catalog``, where the keyset cursor is) and
# must not re-invent the rate limit: this constant is the single place that
# knows what IGDB allows.
IGDB_PAGE_THROTTLE_S = 0.3

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable_error(exc: BaseException) -> bool:
    """True for transient IGDB failures: 429/5xx, timeouts and transport errors.

    Never retries 404 or other 4xx client errors — same policy as
    ``backlogg.movies.adapters.tmdb._is_retryable_error``.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.TimeoutException | httpx.TransportError)


_igdb_retry = retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)

# IGDB category filter clause for get_top_games — e.g. "0,1,2,4,6,7,8,9".
# See backlogg.games.constants for the allowlist this is derived from.
_ALLOWED_CATEGORY_CLAUSE = ",".join(str(i) for i in sorted(ALLOWED_GAME_CATEGORY_IDS))

# The field set every game query asks for. Only the incremental queries below
# use the constant: the three older methods keep their literal so this change
# cannot alter what they request (they are feature 65 / feature 8 code paths
# with their own tests). ``created_at``/``updated_at`` are appended by the
# incremental queries alone — they are the watermark of feature 88 and no other
# caller has any use for them.
_GAME_FIELDS = (
    "name,slug,summary,cover.*,first_release_date,rating,rating_count,"
    "game_type,genres.name,genres.slug,platforms.name,platforms.slug,"
    "involved_companies.company.name,involved_companies.company.slug,"
    "involved_companies.developer,involved_companies.publisher"
)

# How many games one incremental request asks for. IGDB caps a response at 500
# regardless of what ``limit`` says, so this is the ceiling, not a preference.
IGDB_PAGE_SIZE = 500

# ── The catalog filter (feature 65, made explicit by feature 90) ─────────────
#
# The clause that *defines* which games the catalog wants: the ``game_type``
# allowlist (no bundles, mods, ports, packs or updates — issue #14) plus
# ``rating > 0``.  Measured against IGDB on 2026-09-08: 337.291 games pass the
# allowlist, 31.988 of those have a rating.  Dropping ``rating > 0`` would
# multiply the catalog by ten with ~300.000 unrated entries, which is the exact
# noise the filter exists to keep out (docs/seeding-plan.md §2.1).
#
# ``get_top_games`` keeps its own literal copy on purpose: it is a feature-65
# code path with its own tests, and this constant must not be able to change
# what it asks for.
IGDB_CATALOG_WHERE = f"game_type = ({_ALLOWED_CATEGORY_CLAUSE}) & rating > 0"

# What the enumeration asks for per game, and no more: the id, the notoriety
# signal that orders the hydration work list (``rating_count``) and the release
# year.  The enumeration writes no catalog row — the 31.988-row answer to
# "which games does the catalog want" travels in 64 requests because each row
# is three fields instead of twenty.
_CATALOG_ENUMERATION_FIELDS = "id,rating_count,first_release_date"


def parse_igdb_timestamp(value: object) -> datetime | None:
    """Convert an IGDB epoch field (``created_at``/``updated_at``) to a datetime.

    IGDB ships these as Unix seconds. The conversion is explicit and happens
    here, at the adapter boundary, because that is where ``docs/conventions.md``
    puts it (checkpoint C14): the watermark that resumes the incremental is
    derived from these values, and a raw integer travelling into the scheduler
    would be one ``int``/``datetime`` mix-up away from a cursor that no longer
    means an instant. Always UTC-aware — ``set_sync_watermark`` rejects naive
    datetimes on purpose.

    Returns ``None`` for a missing, non-numeric or out-of-range value instead of
    raising: one malformed field must cost that game, not the whole page.
    """
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


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
        """Fetch a single game from IGDB by slug.

        Requests ``similar_games.*`` alongside the usual detail fields so the
        response carries IGDB's own curated relations (id, name, slug, ...)
        for use by the similar-games endpoint, without an extra round trip.
        """
        query = (
            "fields name,slug,summary,cover.*,first_release_date,rating,rating_count,"
            "game_type,genres.name,genres.slug,platforms.name,platforms.slug,"
            "involved_companies.company.name,involved_companies.company.slug,"
            "involved_companies.developer,involved_companies.publisher,similar_games.*;"
            f' where slug = "{slug}";'
            " limit 1;"
        )
        results = await self._post("games", query)
        return results[0] if results else None

    @_igdb_retry
    async def search_games(self, query: str, limit: int = 5, offset: int = 0) -> list[dict]:
        """Search IGDB games by name and return up to ``limit`` results starting at ``offset``.

        ``offset`` follows the same ``offset N;`` clause pattern used by
        ``get_top_games`` — the search fan-out (``search/service.py``) maps
        it from the requested search page to walk further pages of matches.
        """
        escaped = query.replace('"', '\\"')
        igdb_query = (
            "fields name,slug,summary,cover.*,first_release_date,rating,rating_count,"
            "game_type,genres.name,genres.slug,platforms.name,platforms.slug,"
            "involved_companies.company.name,involved_companies.company.slug,"
            "involved_companies.developer,involved_companies.publisher;"
            f' search "{escaped}";'
            f" limit {limit};"
            f" offset {offset};"
        )
        return await self._post("games", igdb_query)

    async def get_top_games(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Fetch top-rated games from IGDB for seeding, restricted to the
        allowed categories (see ``backlogg.games.constants``).

        ``offset`` maps to IGDB's native ``offset N;`` query clause.  IGDB
        caps each request at 500 results, so bigger limits paginate with
        successive requests, sleeping between pages to respect IGDB's
        4 req/s rate limit.  A short page ends the pagination (listing
        exhausted).
        """
        results: list[dict] = []
        current_offset = offset
        while len(results) < limit:
            per_request = min(limit - len(results), 500)
            query = (
                "fields name,slug,summary,cover.*,first_release_date,rating,rating_count,"
                "game_type,genres.name,genres.slug,platforms.name,platforms.slug,"
                "involved_companies.company.name,involved_companies.company.slug,"
                "involved_companies.developer,involved_companies.publisher;"
                f" where game_type = ({_ALLOWED_CATEGORY_CLAUSE}) & rating > 0;"
                " sort rating_count desc;"
                f" limit {per_request};"
                f" offset {current_offset};"
            )
            batch = await self._post("games", query)
            results.extend(batch)
            if len(batch) < per_request:
                break
            current_offset += len(batch)
            if len(results) < limit:
                await asyncio.sleep(IGDB_PAGE_THROTTLE_S)
        return results[:limit]

    # ── Catalog enumeration and hydration by id (feature 90) ─────────────────
    #
    # ``get_top_games`` above walks IGDB's ``rating_count`` ranking by offset,
    # which is what the nightly cursor used to consume.  Feature 90 replaces
    # that with the same two-step split movies and series got in feature 86:
    # *enumerate* which games the catalog wants into ``seed_targets``, then
    # *hydrate* the difference against ``external_ids``.  Two queries, one for
    # each half, and neither of them uses ``offset``.

    @_igdb_retry
    async def get_catalog_page(self, after: int = 0, limit: int = IGDB_PAGE_SIZE) -> list[dict]:
        """One keyset page of the games that pass the catalog filter.

        One page in, one payload out — the loop, the cursor and the throttle
        live in ``backlogg.scheduler.igdb_catalog``, the same separation
        ``discovery.py`` documents for the TMDB ``/discover`` adapters.

        **Keyset, not offset.**  ``where ... & id > {after}; sort id asc`` and
        never ``offset N``.  Offset does work against IGDB all the way to the
        end (measured 2026-09-08: ``offset 31.900`` still answers, unlike
        TMDB's 500-page cap), so this is not a limitation being worked around —
        it is the lesson of ``docs/seeding-plan.md`` §1.  An offset walks a set
        that moves underneath it, and ``rating > 0`` changes on its own as
        players vote: a game crossing the threshold mid-walk shifts every
        later page by one and an already-enumerated game silently drops out of
        the window.  A keyset cut is a concrete id, so that cannot happen.  It
        costs exactly the same 64 requests.

        Retried per page (429/5xx, timeouts, transport errors) rather than per
        walk: re-running the walk would re-request every page already served,
        and IGDB's budget is 4 req/s.
        """
        query = (
            f"fields {_CATALOG_ENUMERATION_FIELDS};"
            f" where {IGDB_CATALOG_WHERE} & id > {int(after)};"
            " sort id asc;"
            f" limit {min(limit, IGDB_PAGE_SIZE)};"
        )
        return await self._post("games", query)

    @_igdb_retry
    async def get_games_by_ids(self, ids: Sequence[str | int]) -> list[dict]:
        """Full payloads for an explicit list of IGDB ids, in one request.

        This is the hydration half, and it is why converting games to
        ``seed_targets`` is cheap where TMDB's was not: TMDB has no bulk detail
        endpoint and pays one request per item, while ``where id = (...)``
        returns up to 500 fully-hydrated games at once.

        No ``game_type``/``rating`` clause: the ids come from the work list,
        which is either a target the enumeration already put through the
        filter or an item the catalog already holds.  Re-applying the filter
        here would make a game that *lost* its rating silently unfetchable —
        it would look like a 404 and get retired — instead of simply refreshed.
        That argument covers ``rating``, which moves on its own; it does not
        cover ``game_type``, which a reclassification can move after the
        enumeration ran.  So the caller re-checks ``game_type`` on the payload
        (``sync_games``), the same way the ``created_at`` lane does: the clause
        is a filter applied by a third party, the check is the gate this
        codebase owns (issue #14).

        An id IGDB does not answer for is absent from the result; the caller
        compares what it asked for against what came back (that is the games
        equivalent of TMDB's 404).  Returns ``[]`` for an empty request without
        touching the network.

        Every id is normalised through ``int`` before it reaches the query, the
        same way ``get_catalog_page`` normalises its keyset cursor.  Apicalypse
        has no bound parameters, so the id list *is* string interpolation; the
        ids in practice come from ``seed_targets``/``external_ids`` and are
        written by this codebase from IGDB's own answers, so today nothing but
        a number can get here — the conversion makes that contract explicit and
        fails loudly with ``ValueError`` if it ever stops holding, instead of
        letting whatever arrived travel into the ``where`` clause.
        """
        try:
            wanted = [str(int(item_id)) for item_id in ids]
        except (TypeError, ValueError) as exc:
            raise ValueError("get_games_by_ids: every id must be a numeric IGDB id") from exc
        if not wanted:
            return []
        if len(wanted) > IGDB_PAGE_SIZE:
            raise ValueError(
                f"get_games_by_ids: {len(wanted)} ids requested but IGDB caps a "
                f"response at {IGDB_PAGE_SIZE} — chunk the list in the caller"
            )
        query = (
            f"fields {_GAME_FIELDS};"
            f" where id = ({','.join(wanted)});"
            " sort id asc;"
            f" limit {len(wanted)};"
        )
        return await self._post("games", query)

    # ── Incremental updates (feature 88) ─────────────────────────────────────
    #
    # IGDB needs no export file and no changes endpoint: its own query language
    # answers "what is new" and "what changed" directly, because every record
    # carries ``created_at`` and ``updated_at``.  Two separate queries and two
    # separate watermarks (``CREATED_AT`` and ``UPDATED_AT``), never one:
    # they can fail independently, and a shared cursor would make a failure of
    # one hold the other back.

    @_igdb_retry
    async def _fetch_games_page(self, query: str) -> list[dict]:
        """One page of an incremental query, with the shared retry policy.

        The retry sits here — on a *single* page — and not on the paginating
        method above it: retrying the walk would re-request every page already
        delivered, and IGDB's budget is 4 req/s. Same policy as
        ``search_games`` (429/5xx, timeouts and transport errors; never a 4xx).
        """
        return await self._post("games", query)

    async def _get_games_since(
        self, field: str, since: datetime, limit: int, offset: int = 0
    ) -> list[dict]:
        """Walk the games whose ``field`` is newer than *since*, oldest first.

        ``field`` is ``created_at`` (new games) or ``updated_at`` (games whose
        record changed).  Three properties of this query are load-bearing:

        - **The category allowlist is in the ``where``.**  A game does not
          enter the catalog just for being new: bundles, mods, ports, packs and
          updates are excluded here exactly as they are in ``get_top_games``
          (feature 65, issue #14).  The caller checks ``game_type`` again on
          the payload — the clause is a filter, the check is the gate.
        - **No ``rating > 0``.**  That clause belongs to the *ranking* walk. A
          game released today has no rating yet, so requiring one here would
          admit nothing at all — the same reason the TMDB lane cannot reuse
          ``vote_count``.
        - **``sort <field> asc``.**  Ascending, so the walk is resumable: the
          caller advances its watermark to the newest value it actually saw,
          and games created *during* the walk land at the end instead of
          shifting the offsets of the pages already read.

        Sleeps ``IGDB_PAGE_THROTTLE_S`` between pages, like ``get_top_games``:
        IGDB allows 4 requests per second.
        """
        cutoff = int(since.timestamp())
        results: list[dict] = []
        current_offset = offset
        while len(results) < limit:
            per_request = min(limit - len(results), IGDB_PAGE_SIZE)
            query = (
                f"fields {_GAME_FIELDS},created_at,updated_at;"
                f" where game_type = ({_ALLOWED_CATEGORY_CLAUSE}) & {field} > {cutoff};"
                f" sort {field} asc;"
                f" limit {per_request};"
                f" offset {current_offset};"
            )
            batch = await self._fetch_games_page(query)
            results.extend(batch)
            if len(batch) < per_request:
                break
            current_offset += len(batch)
            if len(results) < limit:
                await asyncio.sleep(IGDB_PAGE_THROTTLE_S)
        return results[:limit]

    async def get_games_created_since(
        self, since: datetime, limit: int = IGDB_PAGE_SIZE, offset: int = 0
    ) -> list[dict]:
        """Games added to IGDB after *since* — the "new releases" lane."""
        return await self._get_games_since("created_at", since, limit, offset)

    async def get_games_updated_since(
        self, since: datetime, limit: int = IGDB_PAGE_SIZE, offset: int = 0
    ) -> list[dict]:
        """Games whose IGDB record changed after *since* — the "refresh" lane."""
        return await self._get_games_since("updated_at", since, limit, offset)

    def game_to_dict(self, raw: dict) -> dict:
        """Convert an IGDB game object to a DB-ready dict."""
        title = raw.get("name", "")
        # IGDB ships its own slug; only fold the name when it does not.  If
        # neither survives the ASCII fold, fall back to the IGDB id (issue #18)
        # instead of persisting an empty slug.
        slug = raw.get("slug", slugify(title)) or external_id_slug("IGDB", raw.get("id"))

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
        game_type = GAME_TYPE_MAP.get(game_type_int, "MAIN_GAME")

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
            g_slug = g.get("slug") or slugify(g.get("name", ""))
            if g_slug and g_slug not in seen_genres:
                genres.append({"name": g.get("name", g_slug), "slug": g_slug})
                seen_genres.add(g_slug)

        # Platforms
        platforms = []
        seen_platforms: set[str] = set()
        for p in raw.get("platforms") or []:
            if not isinstance(p, dict):
                continue
            p_slug = p.get("slug") or slugify(p.get("name", ""))
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
            c_slug = company.get("slug") or slugify(company.get("name", ""))
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
