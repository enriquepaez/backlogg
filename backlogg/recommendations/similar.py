"""The semantic ``/similar`` of feature 80 — one ranker for the four types.

``GET /{type}/{slug}/similar`` is answered from the HNSW index of feature 75
instead of from each type's own related-items source.  This module is the piece
the four domain services call first; what it returns is already ranked, already
quota'd and already shaped like the response.

Why it lives here and not in ``service.py``
-------------------------------------------

``recommendations/service.py`` imports ``movies.service`` and
``series.service`` for the fan-out of feature 16.  If the four domain services
imported *it* back to reach the ranker, the import graph would close on itself
at module level.  This module imports only the repository, the embedding layer
and the config, so it can be imported from all four without a cycle — the same
reason ``embeddings.py`` and ``wikidata_sync.py`` sit next to the service
rather than inside it.

An item with no vector is not an error
--------------------------------------

Feature 75 embeds a **bounded subset** (``EMBEDDING_MAX_ITEMS``, 40.000).  The
development catalog fits under the cap, but in production roughly 60% of items
will be outside it, and those items still have to answer ``/similar`` as well
as they do today.  So ``get_semantic_similar`` returns ``None`` — not an empty
list — when the vector path has nothing to say, and each caller falls through
to the path it has always used (TMDB recommendations for movies and series,
IGDB ``similar_games`` for games, the local author/genre tiers for books).
**Zero regression** is the requirement, and the "no external calls" clause of
the acceptance list is about the *vector* path, which calls nobody.

``None`` and ``[]`` therefore mean different things and both are load-bearing:
``[]`` would claim "the semantic layer looked and this item genuinely has no
neighbours", which for an unembedded item is a lie that would silently downgrade
60% of the catalog to an empty carousel.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.config import settings
from backlogg.recommendations import repository as repo
from backlogg.recommendations.ranking import (
    SIMILAR_RESULT_LIMIT,
    Candidate,
    rank_similar,
)
from backlogg.shared.item_embeddings import (
    EMBEDDING_ITEM_TYPES,
    SimilarItem,
    get_similar_by_item,
)
from backlogg.shared.schemas import SimilarItemBase, SimilarReason, SimilarReasonKind

__all__ = [
    "SIMILAR_RESULT_LIMIT",
    "cross_type_quota",
    "get_semantic_similar",
    "legacy_reason",
    "to_similar_out",
]


def cross_type_quota(limit: int = SIMILAR_RESULT_LIMIT) -> int:
    """The configured quota, clamped to something a page of ``limit`` can honour.

    Clamped rather than validated at startup: a quota above the page size is a
    misconfiguration whose only sane reading is "all of them", and refusing to
    boot the API over an env var that can be fixed without a deploy would be a
    worse failure than saturating the page.
    """
    return max(0, min(settings.SIMILAR_CROSS_TYPE_QUOTA, limit))


def to_similar_out(candidate: Candidate, reason: SimilarReason) -> SimilarItemBase:
    """One ranked candidate as the shared response row."""
    return SimilarItemBase(
        item_type=candidate.item_type,
        title=candidate.title,
        slug=candidate.slug,
        poster_url=candidate.poster_url,
        release_date=candidate.release_date,
        rating_external=candidate.rating_external,
        rating_internal=candidate.rating_internal,
        reason=reason,
    )


def _semantic_reason(anchor_type: str, candidate: Candidate) -> SimilarReason:
    kind = (
        SimilarReasonKind.SEMANTIC
        if candidate.item_type == anchor_type
        else SimilarReasonKind.SEMANTIC_CROSS_TYPE
    )
    # Rounded because the client shows a percentage and the last digits of a
    # half-precision cosine are quantisation noise, not information.
    return SimilarReason(kind=kind, score=round(candidate.score, 4))


async def _neighbours(
    db: AsyncSession,
    item_type: str,
    item_id: int,
    *,
    limit: int,
    quota: int,
) -> list[SimilarItem]:
    """The candidate pool out of the HNSW index, shaped by the quota.

    The quota does not only *reserve* slots — it decides whether items of
    another type may appear **at all**:

    ``quota <= 0`` (the merged default)
        One read, narrowed to the anchor's own type.  Zero has to mean "never
        another type", not "no slots reserved for another type", because that
        is the property the whole deferral rests on: today
        ``apps/web/src/components/item-similar.tsx`` links every result to
        ``/{type-of-the-page}/{slug}``, so **one** book among films is a 404 in
        production.  Reserving nothing is not enough — an unfiltered cosine
        top-N returns the other types anyway whenever they genuinely win, which
        on the real catalog is 63% of the rows of a film's page.
    ``quota > 0``
        Two reads: the unfiltered top-N, plus a second walk narrowed to the
        *other three* types.  ``item_types`` is a post-filter, so a single
        unfiltered top-N can easily hold zero items of another type — the very
        thing the quota exists to prevent — while the narrowed walk asks the
        index directly for the best neighbours among them.  The two pools are
        merged and de-duplicated.

    Both narrowed walks pass ``ef_search``.  They have to: ``item_types`` is
    applied *after* the index walk, so a narrow type in a skewed catalog comes
    back **empty** at pgvector's default window of 40 — not short, empty.  It
    bites in both directions, and the second one is the less obvious: movies
    are 605 of the 35.215 vectors in the development catalog, so narrowing a
    film's own query to ``MOVIE`` is just as thin a filter as asking a game for
    books.  The measurements are in ``core/config.py``.
    """
    if quota <= 0:
        return await get_similar_by_item(
            db,
            item_type,
            item_id,
            limit=limit,
            item_types=[item_type],
            ef_search=settings.SIMILAR_FILTERED_EF_SEARCH,
        )

    pool = await get_similar_by_item(db, item_type, item_id, limit=limit)
    if not pool:
        return pool

    other_types = sorted(EMBEDDING_ITEM_TYPES - {item_type})
    cross = await get_similar_by_item(
        db,
        item_type,
        item_id,
        limit=limit,
        item_types=other_types,
        ef_search=settings.SIMILAR_FILTERED_EF_SEARCH,
    )
    seen = {(n.item_type, n.item_id) for n in pool}
    pool.extend(n for n in cross if (n.item_type, n.item_id) not in seen)
    return pool


async def get_semantic_similar(
    db: AsyncSession,
    item_type: str,
    item_id: int,
    *,
    limit: int = SIMILAR_RESULT_LIMIT,
) -> list[SimilarItemBase] | None:
    """Ranked neighbours of one item, or ``None`` when there is no vector path.

    ``None`` means "fall back to your own path" and covers both an item outside
    the embedded subset and a subset so empty it has nothing to offer (a fresh
    database, before the monthly job has ever run).  Both are ordinary states,
    not failures.

    The anchor is excluded by ``get_similar_by_item`` itself — cosine with
    itself is exactly 1.0, so without an explicit exclusion every item would be
    its own first recommendation — and excluded again here.  The guard is
    cheap, and the cost of it ever being missing is a result the user reads as
    a bug on the most visible row of the page.
    """
    quota = cross_type_quota(limit)
    pool_size = max(limit, limit * max(1, settings.SIMILAR_CANDIDATE_MULTIPLIER))
    neighbours = await _neighbours(db, item_type, item_id, limit=pool_size, quota=quota)
    neighbours = [n for n in neighbours if (n.item_type, n.item_id) != (item_type, item_id)]
    if not neighbours:
        return None

    rows = await repo.get_similar_candidates(db, [(n.item_type, n.item_id) for n in neighbours])
    candidates: list[Candidate] = []
    for neighbour in neighbours:
        row = rows.get((neighbour.item_type, neighbour.item_id))
        if row is None:
            # The vector outlived the item it described (no FK, by design).
            continue
        candidates.append(
            Candidate(
                item_type=row.item_type,
                item_id=row.item_id,
                title=row.title,
                slug=row.slug,
                poster_url=row.poster_url,
                release_date=row.release_date,
                rating_external=row.rating_external,
                rating_internal=row.rating_internal,
                score=neighbour.score,
                creator_ids=row.creator_ids,
            )
        )
    if not candidates:
        return None

    ranked = rank_similar(
        item_type,
        candidates,
        limit=limit,
        quota=quota,
        penalty=settings.SIMILAR_DIVERSITY_PENALTY,
    )
    return [to_similar_out(c, _semantic_reason(item_type, c)) for c in ranked]


def legacy_reason(
    source: str | None = None, *, kind: SimilarReasonKind | None = None
) -> SimilarReason:
    """The structured reason for a result that did **not** come from a vector.

    Kept next to the semantic one so the vocabulary of ``SimilarReasonKind``
    has a single point of use per kind, instead of four services each building
    a literal.
    """
    if kind is not None:
        return SimilarReason(kind=kind)
    return SimilarReason(kind=SimilarReasonKind.EXTERNAL, source=source)
