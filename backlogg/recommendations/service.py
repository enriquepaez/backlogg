"""Recommendations service — business logic + external fan-out orchestration.

Read-only domain, with two unrelated readers in it:

``get_recommendations``
    builds personalized suggestions for the authenticated user from their
    rating/library seeds. Local genre-overlap candidates come first (via the
    repository); the external similar-items fan-out (feature 16,
    ``movies.service.get_similar_movies`` /
    ``series.service.get_similar_series``) is only triggered for movie/series
    seeds when local candidates are not enough, so we never hit TMDB when the
    catalog already supplies ``needed`` candidates.

``get_item_adaptations``
    serves the cross-media edges feature 79 wrote into ``item_relations``
    (feature 92). Public, anonymous, about one catalog item and not about a
    user — it lives here because this slice owns the Wikidata layer
    (``wikidata_sync.py`` wrote those rows), and it is reached through the four
    content routers, the same way ``ratings.service`` is.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.movies import service as movies_service
from backlogg.ratings import repository as ratings_repo
from backlogg.recommendations import repository as repo
from backlogg.recommendations.schemas import (
    TYPE_FILTER_TO_ITEM_TYPE,
    AdaptationDirection,
    AdaptationOut,
    AdaptationsOut,
    RecommendationOut,
    RecommendationsOut,
)
from backlogg.series import service as series_service
from backlogg.shared.item_relations import (
    RELATION_ADAPTATION,
    RELATION_DERIVATIVE,
    SOURCE_WIKIDATA,
    get_relations_for_item,
)
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
        rating_internal=(float(row.rating_internal) if row.rating_internal is not None else None),
        reason=reason,
    )


async def _external_similar(db: AsyncSession, item_type: str, slug: str):
    """Delegate to the similar-items service of the seed's type.

    Since feature 80 this is no longer only "the external similar-items API":
    the four services answer from the semantic index when the seed has a vector
    and only fall back to TMDB/IGDB when it does not. Two consequences for this
    caller: the fan-out is often free of external calls, and **the results are
    not necessarily of the seed's type** — each row carries its own
    ``item_type`` and it has to be read from there.
    """
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
                    # ``?type=`` is a promise about the whole response, and the
                    # fan-out can now return another type (feature 80). Without
                    # this guard a request for films could come back with a
                    # book in it.
                    if item.item_type not in item_types:
                        continue
                    taken_slugs.add(item.slug)
                    candidates.append(
                        RecommendationOut(
                            # ``item.item_type``, NOT the seed's type. Since
                            # feature 80 the similar-items service answers from
                            # the semantic index and a neighbour of a film can
                            # be a book, so echoing the seed's type here would
                            # label that book ``MOVIE`` and hand the frontend a
                            # link to /movies/{book-slug} — issues #32, #33 and
                            # #36, one endpoint over.
                            item_type=item.item_type,
                            title=item.title,
                            slug=item.slug,
                            poster_url=item.poster_url,
                            release_date=item.release_date,
                            rating_external=item.rating_external,
                            rating_internal=item.rating_internal,
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


# ── Adaptations (feature 92) ──────────────────────────────────────────────────

_ITEM_NOT_FOUND_DETAIL = {
    "MOVIE": "Movie not found",
    "SERIES": "Series not found",
    "BOOK": "Book not found",
    "GAME": "Game not found",
}

# (relation, the anchor is the ``from`` end) -> where the *other* end sits.
#
# ``ADAPTATION`` means "from is based on to" and ``DERIVATIVE`` means "to is
# derived from from" (``shared/item_relations.py``), so the same relation reads
# in opposite directions depending on which side the item in the URL is on —
# which is exactly why the direction has to be resolved here and not left to
# the client.
_DIRECTION_OF_OTHER_END = {
    (RELATION_ADAPTATION, True): AdaptationDirection.SOURCE,
    (RELATION_ADAPTATION, False): AdaptationDirection.DERIVED,
    (RELATION_DERIVATIVE, True): AdaptationDirection.DERIVED,
    (RELATION_DERIVATIVE, False): AdaptationDirection.SOURCE,
}


async def get_item_adaptations(db: AsyncSession, item_type: str, slug: str) -> AdaptationsOut:
    """Cross-media adaptations of one catalog item, both directions resolved.

    404 is reserved for a slug that names no item. An item that simply has no
    adaptations returns ``200`` with an empty list, and that is the **normal**
    case, not an error: the Wikidata pass is precise and sparse by design (18
    edges over 1.092 anchored items in the feature 79 QA), so most of the
    catalog will answer empty forever. A 404 there would make the frontend
    treat the ordinary case as a failure.

    Only ``source='WIKIDATA'`` rows are returned. Feature 83 will write
    ``INTERNAL``/``COOCCURRENCE`` edges into the very same table, and they are
    a different kind of claim — an adaptation is a fact somebody asserted, a
    co-occurrence is an inference from behaviour. Letting the second leak into
    the "based on" section would quietly turn it into something else, so the
    filter is applied at the read and not left to whoever queries.
    """
    item = await ratings_repo.get_item_by_slug(db, item_type, slug)
    if item is None:
        raise HTTPException(status_code=404, detail=_ITEM_NOT_FOUND_DETAIL[item_type])

    edges = await get_relations_for_item(db, item_type, item.id, source=SOURCE_WIKIDATA)

    # (far end, direction), in the repository's order (score desc, id asc).
    ends: list[tuple[tuple[str, int], AdaptationDirection]] = []
    for edge in edges:
        anchor_is_from = edge.from_type == item_type and edge.from_id == item.id
        direction = _DIRECTION_OF_OTHER_END.get((edge.relation, anchor_is_from))
        if direction is None:
            # A relation outside the adaptation vocabulary (today only
            # COOCCURRENCE, which no WIKIDATA row carries). Skipped rather
            # than shown under a direction that would be invented for it.
            continue
        far_end = (edge.to_type, edge.to_id) if anchor_is_from else (edge.from_type, edge.from_id)
        ends.append((far_end, direction))

    refs = await repo.get_item_refs(db, {far_end for far_end, _ in ends})

    results: list[AdaptationOut] = []
    seen: set[tuple[tuple[str, int], AdaptationDirection]] = set()
    for far_end, direction in ends:
        ref = refs.get(far_end)
        if ref is None:
            continue
        # ``P144`` and ``P4969`` are declared inverses in Wikidata, so a
        # well-curated pair arrives as two rows saying the same thing from
        # opposite ends, and both are stored (the unique key carries
        # ``relation``). They collapse to one entry here: same neighbour, same
        # direction, one line in the UI.
        key = (far_end, direction)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            AdaptationOut(
                item_type=ref.item_type,
                slug=ref.slug,
                title=ref.title,
                poster_url=ref.poster_url,
                direction=direction,
            )
        )
    return AdaptationsOut(results=results)
