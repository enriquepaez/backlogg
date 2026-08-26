import asyncio
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books import repository as books_repo
from backlogg.books.models import Book
from backlogg.books.schemas import BookSortEnum
from backlogg.core.cache import get_cache
from backlogg.core.config import settings
from backlogg.games import repository as games_repo
from backlogg.games.models import Game
from backlogg.games.schemas import GameSortEnum
from backlogg.movies import repository as movies_repo
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.adapters.tmdb import _slugify as _movie_slugify
from backlogg.series import repository as series_repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.series.adapters.tmdb import _slugify as _series_slugify
from backlogg.shared.external_ids import upsert_external_id
from backlogg.trending.schemas import TrendingItemOut, TrendingOut

_movies_tmdb = TMDBClient()
_series_tmdb = TMDBSeriesClient()


async def _ingest_trending_movie(db: AsyncSession, raw: dict) -> TrendingItemOut | None:
    """Persist a trending movie (list-format TMDB item) and return a TrendingItemOut.

    The trending endpoint returns list-format items (no genres), so we fetch
    full detail to get genres and persist correctly.
    """
    tmdb_id = raw.get("id")
    if not tmdb_id:
        return None

    title = raw.get("title", "")
    release_date_str = raw.get("release_date", "")
    release_date: date | None = None
    year = ""
    if release_date_str:
        try:
            release_date = date.fromisoformat(release_date_str)
            year = str(release_date.year)
        except ValueError:
            pass

    slug_base = _movie_slugify(title)
    slug = f"{slug_base}-{year}" if year else slug_base

    # Try local DB first to avoid unnecessary TMDB calls
    movie = await movies_repo.get_movie_by_slug(db, slug)
    if movie is None:
        detail = await _movies_tmdb.get_movie_detail(tmdb_id)
        if detail is None:
            return None
        movie_data = _movies_tmdb.movie_to_dict(detail)
        movie = await movies_repo.upsert_movie(db, movie_data)
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", str(tmdb_id))
        await db.commit()

    poster_path = raw.get("poster_path")
    poster_url = (
        f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else movie.poster_url
    )

    vote_average = raw.get("vote_average")
    rating_external = (
        round(float(vote_average), 1)
        if vote_average
        else (float(movie.rating_external) if movie.rating_external is not None else None)
    )

    return TrendingItemOut(
        item_type="MOVIE",
        title=movie.title,
        slug=movie.slug,
        poster_url=poster_url,
        release_date=movie.release_date,
        rating_external=rating_external,
        rating_internal=(
            float(movie.rating_internal) if movie.rating_internal is not None else None
        ),
    )


async def _ingest_trending_series(db: AsyncSession, raw: dict) -> TrendingItemOut | None:
    """Persist a trending series (list-format TMDB item) and return a TrendingItemOut."""
    tmdb_id = raw.get("id")
    if not tmdb_id:
        return None

    title = raw.get("name", "")
    first_air_date_str = raw.get("first_air_date", "")
    year = ""
    if first_air_date_str:
        try:
            first_air_date = date.fromisoformat(first_air_date_str)
            year = str(first_air_date.year)
        except ValueError:
            pass

    slug_base = _series_slugify(title)
    slug = f"{slug_base}-{year}" if year else slug_base

    series = await series_repo.get_series_by_slug(db, slug)
    if series is None:
        detail = await _series_tmdb.get_series_detail(tmdb_id)
        if detail is None:
            return None
        series_data = _series_tmdb.series_to_dict(detail)
        series = await series_repo.upsert_series(db, series_data)
        await upsert_external_id(db, "SERIES", series.id, "TMDB", str(tmdb_id))
        await db.commit()

    poster_path = raw.get("poster_path")
    poster_url = (
        f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else series.poster_url
    )

    vote_average = raw.get("vote_average")
    rating_external = (
        round(float(vote_average), 1)
        if vote_average
        else (float(series.rating_external) if series.rating_external is not None else None)
    )

    return TrendingItemOut(
        item_type="SERIES",
        title=series.title,
        slug=series.slug,
        poster_url=poster_url,
        release_date=series.first_air_date,
        rating_external=rating_external,
        rating_internal=(
            float(series.rating_internal) if series.rating_internal is not None else None
        ),
    )


def _book_to_trending_item(book: Book) -> TrendingItemOut:
    """Map a persisted ``Book`` to a trending item.

    Books have no external "trending this week" endpoint (Open Library
    exposes no such thing), so unlike movies/series there is nothing to
    ingest here — the item is already in the catalog. Popularity is a local
    heuristic instead of a fetched signal (see ``_collect_books``).
    """
    return TrendingItemOut(
        item_type="BOOK",
        title=book.title,
        slug=book.slug,
        poster_url=book.poster_url,
        release_date=book.first_publish_date,
        rating_external=(float(book.rating_external) if book.rating_external is not None else None),
        rating_internal=(float(book.rating_internal) if book.rating_internal is not None else None),
    )


def _game_to_trending_item(game: Game) -> TrendingItemOut:
    """Map a persisted ``Game`` to a trending item (see ``_book_to_trending_item``).

    IGDB has no "trending this week" endpoint either, so games use the same
    local popularity heuristic as books.
    """
    return TrendingItemOut(
        item_type="GAME",
        title=game.title,
        slug=game.slug,
        poster_url=game.poster_url,
        release_date=game.release_date,
        rating_external=(float(game.rating_external) if game.rating_external is not None else None),
        rating_internal=(float(game.rating_internal) if game.rating_internal is not None else None),
    )


async def _collect_books(db: AsyncSession, limit: int) -> list[TrendingItemOut]:
    """Return up to ``limit`` books ranked by the catalog's popularity heuristic.

    Open Library has no native "trending" concept, so this reuses the same
    ``order_by`` already established for book listings (feature 66):
    ``rating_internal DESC NULLS LAST`` as the primary/visible criterion,
    ``rating_external DESC NULLS LAST`` only as an internal tie-break. This
    is a local ranking over already-persisted items, not an external fetch —
    there is nothing to ingest, unlike movies/series.
    """
    books, _total = await books_repo.list_books(
        db, genre=None, sort=BookSortEnum.rating_desc, page=1, limit=limit
    )
    return [_book_to_trending_item(book) for book in books]


async def _collect_games(db: AsyncSession, limit: int) -> list[TrendingItemOut]:
    """Return up to ``limit`` games ranked by the same popularity heuristic
    as ``_collect_books`` (IGDB also has no native "trending" concept)."""
    games, _total = await games_repo.list_games(
        db, genre=None, sort=GameSortEnum.rating_desc, page=1, limit=limit
    )
    return [_game_to_trending_item(game) for game in games]


def _interleave(*lists: list[TrendingItemOut]) -> list[TrendingItemOut]:
    """Round-robin interleave any number of result lists.

    Preserves each list's internal order. Lists shorter than the longest one
    simply stop contributing once exhausted — no items are dropped for the
    lists that have more available, unlike a naive zip().
    """
    interleaved: list[TrendingItemOut] = []
    max_len = max((len(lst) for lst in lists), default=0)
    for i in range(max_len):
        for lst in lists:
            if i < len(lst):
                interleaved.append(lst[i])
    return interleaved


async def _collect_movies(db: AsyncSession, raw_list: list[dict]) -> list[TrendingItemOut]:
    """Process trending movies sequentially (same DB session — no concurrency)."""
    results: list[TrendingItemOut] = []
    for raw in raw_list:
        try:
            item = await _ingest_trending_movie(db, raw)
            if item is not None:
                results.append(item)
        except Exception:
            pass  # skip items that fail to ingest
    return results


async def _collect_series(db: AsyncSession, raw_list: list[dict]) -> list[TrendingItemOut]:
    """Process trending series sequentially (same DB session — no concurrency)."""
    results: list[TrendingItemOut] = []
    for raw in raw_list:
        try:
            item = await _ingest_trending_series(db, raw)
            if item is not None:
                results.append(item)
        except Exception:
            pass  # skip items that fail to ingest
    return results


async def get_trending(
    db: AsyncSession,
    item_type: str | None,
    period: str,
) -> TrendingOut:
    """Return up to 20 trending items, served from the in-process TTL cache.

    Trending is expensive — it fans out to TMDB and may ingest new items — so the
    computed result is cached per ``(item_type, period)`` for a configurable TTL.
    The cache lives behind ``get_cache()`` so it can move to Redis without
    touching this call site. A cache miss recomputes via :func:`_compute_trending`.
    """
    cache = get_cache()
    key = f"trending:{item_type}:{period}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    result = await _compute_trending(db, item_type=item_type, period=period)
    cache.set(key, result, settings.CACHE_TTL_TRENDING)
    return result


async def _compute_trending(
    db: AsyncSession,
    item_type: str | None,
    period: str,
) -> TrendingOut:
    """Compute the trending list (uncached).

    - item_type=None   → mix of the 4 types (movies, series, books, games),
      up to 5 each, interleaved
    - item_type=movie  → movies only (TMDB trending, ``period`` applies)
    - item_type=series → series only (TMDB trending, ``period`` applies)
    - item_type=book   → books only, ranked by the local popularity heuristic
      (feature 68 — Open Library has no "trending" endpoint). ``period`` is
      accepted but ignored: the heuristic has no time window.
    - item_type=game   → games only, same local heuristic as books (IGDB has
      no "trending" endpoint either). ``period`` is accepted but ignored.
    """
    if item_type == "movie":
        raw_movies = await _movies_tmdb.get_trending_movies(period)
        results = await _collect_movies(db, raw_movies[:20])
        return TrendingOut(results=results[:20])

    if item_type == "series":
        raw_series = await _series_tmdb.get_trending_series(period)
        results = await _collect_series(db, raw_series[:20])
        return TrendingOut(results=results[:20])

    if item_type == "book":
        results = await _collect_books(db, limit=20)
        return TrendingOut(results=results[:20])

    if item_type == "game":
        results = await _collect_games(db, limit=20)
        return TrendingOut(results=results[:20])

    # No type filter — mix of the 4 types. Movies/series come from TMDB
    # (fetched concurrently, no DB involved), books/games from the local
    # heuristic. Each processed sequentially against the same DB session to
    # avoid concurrent writes on it.
    raw_movies, raw_series = await asyncio.gather(
        _movies_tmdb.get_trending_movies(period),
        _series_tmdb.get_trending_series(period),
    )

    movies_out = await _collect_movies(db, raw_movies[:5])
    series_out = await _collect_series(db, raw_series[:5])
    books_out = await _collect_books(db, limit=5)
    games_out = await _collect_games(db, limit=5)

    interleaved = _interleave(movies_out, series_out, books_out, games_out)
    return TrendingOut(results=interleaved[:20])
