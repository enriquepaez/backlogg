"""Recommendations service — business logic + external fan-out orchestration.

Read-only domain: builds personalized suggestions for the authenticated user
from their rating/library seeds. Local genre-overlap candidates come first
(via the repository); the external similar-items fan-out (feature 16,
``movies.service.get_similar_movies`` / ``series.service.get_similar_series``)
is only triggered for movie/series seeds when local candidates are not enough,
so we never hit TMDB when the catalog already supplies ``needed`` candidates.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.movies import service as movies_service
from backlogg.recommendations import repository as repo
from backlogg.recommendations.schemas import (
    TYPE_FILTER_TO_ITEM_TYPE,
    RecommendationOut,
    RecommendationsOut,
)
from backlogg.series import service as series_service
from backlogg.users.models import User

_ALL_ITEM_TYPES = ["MOVIE", "SERIES", "BOOK", "GAME"]
# Types that have an external similar-items API (feature 16).
_EXTERNAL_TYPES = ("MOVIE", "SERIES")
# How many top seeds per type to fan out on when local candidates fall short.
_MAX_SEEDS_FANOUT = 3


def _seed_reason(seed) -> str:
    if seed.source == "rated":
        return f"Because you rated {seed.title}"
    return f"Because {seed.title} is in your library"


def _row_to_rec(item_type: str, row, reason: str) -> RecommendationOut:
    return RecommendationOut(
        item_type=item_type,
        title=row.title,
        slug=row.slug,
        poster_url=row.poster_url,
        release_date=row.release_date,
        rating_external=(float(row.rating_external) if row.rating_external is not None else None),
        reason=reason,
    )


async def _external_similar(db: AsyncSession, item_type: str, slug: str):
    """Delegate to feature 16's similar-items service for the given type."""
    if item_type == "MOVIE":
        return (await movies_service.get_similar_movies(db, slug)).results
    return (await series_service.get_similar_series(db, slug)).results


async def get_recommendations(
    db: AsyncSession,
    user: User,
    type_filter: str | None,
    page: int,
    limit: int,
) -> RecommendationsOut:
    item_types = [TYPE_FILTER_TO_ITEM_TYPE[type_filter]] if type_filter else list(_ALL_ITEM_TYPES)
    needed = page * limit

    seeds = await repo.get_seeds(db, user.id, item_types)
    seen_ids = await repo.get_seen_item_ids(db, user.id)

    # ── No seeds → popular/trending fallback (local, never empty with catalog) ──
    if not seeds:
        rows = await repo.get_popular_items(db, item_types, seen_ids, limit=needed)
        results = [_row_to_rec(row.item_type, row, "Popular right now") for row in rows]
        return _paginate(results, page, limit)

    seeds_by_type: dict[str, list] = {t: [] for t in item_types}
    for seed in seeds:
        seeds_by_type[seed.item_type].append(seed)

    taken_slugs: set[str] = set()
    per_type_candidates: dict[str, list[RecommendationOut]] = {t: [] for t in item_types}

    # ── Phase 1: local genre-overlap candidates for every type with seeds ──
    for item_type in item_types:
        type_seeds = seeds_by_type[item_type]
        if not type_seeds:
            continue
        excluded = {iid for (it, iid) in seen_ids if it == item_type}
        rows = await repo.get_genre_overlap_candidates(
            db,
            item_type,
            [s.item_id for s in type_seeds],
            excluded,
            limit=needed,
        )
        reason = _seed_reason(type_seeds[0])
        for row in rows:
            if row.slug in taken_slugs:
                continue
            taken_slugs.add(row.slug)
            per_type_candidates[item_type].append(_row_to_rec(item_type, row, reason))

    candidates = _interleave([per_type_candidates[t] for t in item_types])

    # ── Phase 2: external fan-out only if locals fall short (movies/series) ──
    if len(candidates) < needed:
        seen_slugs = await repo.get_seen_slugs(db, user.id)
        for item_type in item_types:
            if item_type not in _EXTERNAL_TYPES:
                continue
            for seed in seeds_by_type[item_type][:_MAX_SEEDS_FANOUT]:
                if len(candidates) >= needed:
                    break
                similar = await _external_similar(db, item_type, seed.slug)
                reason = _seed_reason(seed)
                for item in similar:
                    if item.slug in taken_slugs or item.slug in seen_slugs:
                        continue
                    taken_slugs.add(item.slug)
                    candidates.append(
                        RecommendationOut(
                            item_type=item_type,
                            title=item.title,
                            slug=item.slug,
                            poster_url=item.poster_url,
                            release_date=item.release_date,
                            rating_external=item.rating_external,
                            reason=reason,
                        )
                    )
            if len(candidates) >= needed:
                break

    return _paginate(candidates, page, limit)


def _interleave(lists: list[list]) -> list:
    """Round-robin merge of per-type candidate lists so types are mixed."""
    merged = []
    i = 0
    while True:
        added = False
        for lst in lists:
            if i < len(lst):
                merged.append(lst[i])
                added = True
        if not added:
            break
        i += 1
    return merged


def _paginate(results: list[RecommendationOut], page: int, limit: int) -> RecommendationsOut:
    start = (page - 1) * limit
    page_items = results[start : start + limit]
    return RecommendationsOut(results=page_items, page=page, limit=limit)
