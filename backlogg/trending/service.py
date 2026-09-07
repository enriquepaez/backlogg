"""Trending service — ranking built from the platform's own recent activity.

Feature 81. ``GET /v1/trending`` no longer asks TMDB what the rest of the
internet is watching: it ranks by what *this* community did in the last
``period``, with an explicit exponential time decay. There is no external
fan-out left in this module, which also means trending no longer discovers or
ingests new catalog items — the catalog is filled by the seeding scripts and
by the nightly sync (see ``docs/seeding-plan.md``).

Two sources, chosen **per item type**:

1. **Local activity** — ``activity_events`` + ``library_entries`` +
   ``user_ratings`` inside the period's window, decayed by age. Served when the
   type has at least ``settings.TRENDING_MIN_ACTIVITY`` gestures in that
   window. The de-duplicated decomposition of those three tables (they overlap
   by construction) is documented in ``backlogg/trending/repository.py``.
2. **Fallback** — the catalog's canonical order (feature 66:
   ``rating_internal DESC NULLS LAST``, ``rating_external DESC NULLS LAST`` as
   tie-break) restricted to recent releases. The period lives in the ``WHERE``
   (a release-date window), never in the ``ORDER BY``, which is what makes
   ``period`` observable even with an empty platform — the default state until
   the community exists.

The threshold is evaluated per type, not globally: books can rank from real
activity while games still fall back, inside the same response.
"""

from datetime import UTC, datetime, timedelta

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
from backlogg.movies.models import Movie
from backlogg.movies.schemas import MovieSortEnum
from backlogg.series import repository as series_repo
from backlogg.series.models import Series
from backlogg.series.schemas import SeriesSortEnum
from backlogg.shared.catalog_filters import CatalogSearchFilters
from backlogg.trending import repository as repo
from backlogg.trending.schemas import TrendingItemOut, TrendingOut

TRENDING_LIMIT = 20
MIX_PER_TYPE = 5

# ── What ``period`` means ────────────────────────────────────────────────────
#
# ACTIVITY_WINDOWS is how far back the activity signal looks. DECAY_HALF_LIVES
# is the half-life of that signal inside the window: a gesture exactly one
# half-life old counts half as much as one made right now, two half-lives a
# quarter, and so on (``0.5 ** (age / half_life)``). Both are a quarter of the
# window, so the newest quarter of the window always dominates — that is what
# makes "trending" mean *accelerating*, not merely *popular*.
ACTIVITY_WINDOWS: dict[str, timedelta] = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
}
DECAY_HALF_LIVES: dict[str, timedelta] = {
    "day": timedelta(hours=6),
    "week": timedelta(hours=42),
}

# Release-date window used by the fallback. Much wider than the activity
# window, because it filters *catalog* recency rather than user gestures: what
# counts as "a recent release" is measured in months, not hours. Still driven
# by ``period``, so the parameter has a real effect for all four types even
# with zero activity on the platform.
FALLBACK_WINDOWS: dict[str, timedelta] = {
    "day": timedelta(days=90),
    "week": timedelta(days=365),
}

# ?type= value -> stored item_type (the three activity tables and the four
# catalog tables both use the uppercase form).
TYPE_TO_ITEM_TYPE: dict[str, str] = {
    "movie": "MOVIE",
    "series": "SERIES",
    "book": "BOOK",
    "game": "GAME",
}


# ── Mapping catalog rows to the response shape ───────────────────────────────


def _movie_to_trending_item(movie: Movie) -> TrendingItemOut:
    return TrendingItemOut(
        item_type="MOVIE",
        title=movie.title,
        slug=movie.slug,
        poster_url=movie.poster_url,
        release_date=movie.release_date,
        rating_external=(
            float(movie.rating_external) if movie.rating_external is not None else None
        ),
        rating_internal=(
            float(movie.rating_internal) if movie.rating_internal is not None else None
        ),
    )


def _series_to_trending_item(series: Series) -> TrendingItemOut:
    return TrendingItemOut(
        item_type="SERIES",
        title=series.title,
        slug=series.slug,
        poster_url=series.poster_url,
        release_date=series.first_air_date,
        rating_external=(
            float(series.rating_external) if series.rating_external is not None else None
        ),
        rating_internal=(
            float(series.rating_internal) if series.rating_internal is not None else None
        ),
    )


def _book_to_trending_item(book: Book) -> TrendingItemOut:
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
    return TrendingItemOut(
        item_type="GAME",
        title=game.title,
        slug=game.slug,
        poster_url=game.poster_url,
        release_date=game.release_date,
        rating_external=(float(game.rating_external) if game.rating_external is not None else None),
        rating_internal=(float(game.rating_internal) if game.rating_internal is not None else None),
    )


_TO_TRENDING_ITEM = {
    "MOVIE": _movie_to_trending_item,
    "SERIES": _series_to_trending_item,
    "BOOK": _book_to_trending_item,
    "GAME": _game_to_trending_item,
}


# ── Fallback: canonical catalog order, restricted to recent releases ─────────


async def _list_recent_catalog(
    db: AsyncSession, item_type: str, date_from, limit: int
) -> list[TrendingItemOut]:
    """One page of the type's catalog listing, newest-release window applied.

    Delegates to the domain's own ``list_*`` repository rather than re-writing
    its ``ORDER BY`` here: trending must rank like the rest of the catalog, and
    both the sort (``rating_desc``) and the date window (``filters.date_from``,
    already bound to each type's own date column) are part of those functions'
    existing contract. ``date_from=None`` means "no window".
    """
    filters = CatalogSearchFilters(date_from=date_from)
    if item_type == "MOVIE":
        items, _ = await movies_repo.list_movies(
            db, genre=None, sort=MovieSortEnum.rating_desc, page=1, limit=limit, filters=filters
        )
    elif item_type == "SERIES":
        items, _ = await series_repo.list_series(
            db, genre=None, sort=SeriesSortEnum.rating_desc, page=1, limit=limit, filters=filters
        )
    elif item_type == "BOOK":
        items, _ = await books_repo.list_books(
            db, genre=None, sort=BookSortEnum.rating_desc, page=1, limit=limit, filters=filters
        )
    else:
        items, _ = await games_repo.list_games(
            db, genre=None, sort=GameSortEnum.rating_desc, page=1, limit=limit, filters=filters
        )
    to_item = _TO_TRENDING_ITEM[item_type]
    return [to_item(item) for item in items]


async def _fallback(
    db: AsyncSession, item_type: str, period: str, limit: int
) -> list[TrendingItemOut]:
    """Catalog fallback for one type: recent releases in canonical order.

    Empty-window edge case: a catalog with no release of this type inside the
    window would otherwise leave a silent hole in the response — worse for the
    caller than a slightly older item, and the likeliest outcome for books,
    whose ``first_publish_date`` is the original publication year. So when the
    window yields **nothing at all**, it is relaxed away entirely and the plain
    canonical order is served. The window is only relaxed on a *fully* empty
    result: a partial one still honours ``period``, which is the point of the
    parameter.
    """
    cutoff = (datetime.now(UTC) - FALLBACK_WINDOWS[period]).date()
    items = await _list_recent_catalog(db, item_type, cutoff, limit)
    if items:
        return items
    return await _list_recent_catalog(db, item_type, None, limit)


# ── Local activity ranking ───────────────────────────────────────────────────


async def _local_activity(
    db: AsyncSession, item_type: str, period: str, limit: int
) -> list[TrendingItemOut] | None:
    """Top ``limit`` items of this type by decayed local activity.

    Returns ``None`` when the type has fewer than ``TRENDING_MIN_ACTIVITY``
    gestures inside the window — the signal is too thin to rank on, so the
    caller falls back. That decision is taken per type.

    Two queries total, never one per item: one aggregate over the activity
    tables, one batch resolution of the winning ids against the catalog table.
    An id whose catalog row no longer exists is dropped silently (the activity
    tables are polymorphic and carry no FK).
    """
    now = datetime.now(UTC)
    since = now - ACTIVITY_WINDOWS[period]
    half_life_seconds = DECAY_HALF_LIVES[period].total_seconds()

    total_gestures, scored = await repo.activity_scores(
        db,
        item_type=item_type,
        since=since,
        now=now,
        half_life_seconds=half_life_seconds,
        limit=limit,
    )
    if total_gestures < settings.TRENDING_MIN_ACTIVITY:
        return None

    rows = await repo.get_items_by_ids(db, item_type, [item_id for item_id, _ in scored])
    to_item = _TO_TRENDING_ITEM[item_type]
    return [to_item(rows[item_id]) for item_id, _ in scored if item_id in rows]


async def _collect(
    db: AsyncSession, item_type: str, period: str, limit: int
) -> list[TrendingItemOut]:
    """Local activity for this type if there is enough of it, catalog otherwise."""
    items = await _local_activity(db, item_type, period, limit)
    if items:
        return items
    return await _fallback(db, item_type, period, limit)


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


# ── Entry point ──────────────────────────────────────────────────────────────


async def get_trending(
    db: AsyncSession,
    item_type: str | None,
    period: str,
) -> TrendingOut:
    """Return up to 20 trending items, served from the in-process TTL cache.

    Trending aggregates over three activity tables plus the catalog, so the
    computed result is cached per ``(item_type, period)`` for a configurable
    TTL. The cache lives behind ``get_cache()`` so it can move to Redis without
    touching this call site. A cache miss recomputes via
    :func:`_compute_trending`.
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

    - ``item_type=None`` → mix of the four types, up to 5 each, interleaved.
      Each block resolves its own source independently, so one type falling
      back does not drag the others with it.
    - ``item_type=movie|series|book|game`` → that type only, up to 20.

    ``period`` applies to all four types, in both branches: it sets the
    activity window and its decay half-life, and the release-date window of
    the fallback.
    """
    period = str(period)
    if item_type is not None:
        stored_type = TYPE_TO_ITEM_TYPE[str(item_type)]
        results = await _collect(db, stored_type, period, TRENDING_LIMIT)
        return TrendingOut(results=results[:TRENDING_LIMIT])

    blocks = [
        await _collect(db, stored_type, period, MIX_PER_TYPE)
        for stored_type in TYPE_TO_ITEM_TYPE.values()
    ]
    return TrendingOut(results=_interleave(*blocks)[:TRENDING_LIMIT])
