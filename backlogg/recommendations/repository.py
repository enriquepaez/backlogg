"""Recommendations repository — read-only DB queries.

Only this file imports and uses SQLAlchemy for the recommendations domain. It
reuses the polymorphic ``item_type``/``item_id`` model mapping from
``backlogg/ratings/repository.py`` (``ITEM_MODELS``) and the ``LibraryEntry`` /
``UserRating`` tables, and builds cross-type reads with the same ``union_all``
style as ``backlogg/feed/repository.py`` and ``backlogg/library/repository.py``.

Nothing here writes; recommendations are computed, never persisted.
"""

from typing import Any

from sqlalchemy import String, and_, case, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from backlogg.books.models import Book, book_genres_join
from backlogg.games.models import Game, game_genres_join
from backlogg.library.models import LibraryEntry
from backlogg.movies.models import Movie, movie_genres_join
from backlogg.ratings.models import UserRating
from backlogg.series.models import Series, series_genres_join
from backlogg.shared.credits import AUTHORSHIP_ROLES
from backlogg.shared.models import Credit

# Statuses that count as an implicit positive signal for seeding.
SEED_LIBRARY_STATUSES = ("completed", "want")
# Minimum explicit rating that counts as a seed.
SEED_MIN_SCORE = 4

# Per item_type: (content model, genre join table, join item-id column name,
# release-date column name). Mirrors library/repository._RELEASE_DATE_ATTR but
# also carries the many-to-many join needed for genre-overlap heuristics.
_TYPE_CONFIG: dict[str, tuple[type[DeclarativeBase], Any, str, str]] = {
    "MOVIE": (Movie, movie_genres_join, "movie_id", "release_date"),
    "SERIES": (Series, series_genres_join, "series_id", "first_air_date"),
    "BOOK": (Book, book_genres_join, "book_id", "first_publish_date"),
    "GAME": (Game, game_genres_join, "game_id", "release_date"),
}


def _release_col(item_type: str):
    model, _join, _item_col, release_attr = _TYPE_CONFIG[item_type]
    return getattr(model, release_attr)


async def get_seeds(db: AsyncSession, user_id: int, item_types: list[str]) -> list[Any]:
    """Return the user's seed items across ``item_types``, strongest first.

    A seed is any item the user rated with a score >= ``SEED_MIN_SCORE`` or has
    in their library with status in ``SEED_LIBRARY_STATUSES``. Each row carries
    ``item_type``, ``item_id``, ``slug``, ``title``, a numeric ``weight`` and a
    ``source`` ('rated' or 'library') so the service can build a human reason
    and prioritise stronger signals. Deduplicated per (item_type, item_id),
    keeping the highest-weight/ rated-over-library occurrence.
    """
    queries = []
    for item_type in item_types:
        model, _join, _item_col, _release_attr = _TYPE_CONFIG[item_type]

        rated = (
            select(
                literal(item_type, type_=String).label("item_type"),
                model.id.label("item_id"),
                model.slug.label("slug"),
                model.title.label("title"),
                UserRating.score.label("weight"),
                literal("rated", type_=String).label("source"),
            )
            .join(
                UserRating,
                and_(
                    UserRating.item_id == model.id,
                    UserRating.item_type == item_type,
                ),
            )
            .where(UserRating.user_id == user_id, UserRating.score >= SEED_MIN_SCORE)
        )

        library = (
            select(
                literal(item_type, type_=String).label("item_type"),
                model.id.label("item_id"),
                model.slug.label("slug"),
                model.title.label("title"),
                case((LibraryEntry.status == "completed", 4), else_=3).label("weight"),
                literal("library", type_=String).label("source"),
            )
            .join(
                LibraryEntry,
                and_(
                    LibraryEntry.item_id == model.id,
                    LibraryEntry.item_type == item_type,
                ),
            )
            .where(
                LibraryEntry.user_id == user_id,
                LibraryEntry.status.in_(SEED_LIBRARY_STATUSES),
            )
        )
        queries.append(rated)
        queries.append(library)

    combined = union_all(*queries) if len(queries) > 1 else queries[0]
    result = await db.execute(select(combined.subquery()))
    rows = list(result.all())

    # Order by strongest signal (higher weight, rated over library) and dedupe
    # per (item_type, item_id) keeping the first — done in Python so the same
    # item rated *and* in the library collapses to a single seed.
    rows.sort(key=lambda r: (-r.weight, 0 if r.source == "rated" else 1))
    seen: set[tuple[str, int]] = set()
    seeds = []
    for row in rows:
        key = (row.item_type, row.item_id)
        if key in seen:
            continue
        seen.add(key)
        seeds.append(row)
    return seeds


async def get_seen_item_ids(db: AsyncSession, user_id: int) -> set[tuple[str, int]]:
    """Return every (item_type, item_id) the user has rated or has in library.

    Used to exclude already-seen items from recommendations (regardless of
    score or status — any interaction counts as "seen").
    """
    result = await db.execute(
        select(UserRating.item_type, UserRating.item_id).where(UserRating.user_id == user_id)
    )
    seen = {(r.item_type, r.item_id) for r in result.all()}

    result = await db.execute(
        select(LibraryEntry.item_type, LibraryEntry.item_id).where(LibraryEntry.user_id == user_id)
    )
    seen |= {(r.item_type, r.item_id) for r in result.all()}
    return seen


async def get_seen_slugs(db: AsyncSession, user_id: int) -> set[str]:
    """Return the slugs of every item the user has rated or has in library.

    Slug-based exclusion for candidates that only expose a slug (e.g. the
    external similar-items results, which are not queried by id).
    """
    slugs: set[str] = set()
    for item_type, (model, _join, _item_col, _release_attr) in _TYPE_CONFIG.items():
        result = await db.execute(
            select(model.slug)
            .join(
                UserRating,
                and_(UserRating.item_id == model.id, UserRating.item_type == item_type),
            )
            .where(UserRating.user_id == user_id)
        )
        slugs |= {r[0] for r in result.all()}

        result = await db.execute(
            select(model.slug)
            .join(
                LibraryEntry,
                and_(LibraryEntry.item_id == model.id, LibraryEntry.item_type == item_type),
            )
            .where(LibraryEntry.user_id == user_id)
        )
        slugs |= {r[0] for r in result.all()}
    return slugs


async def get_genre_overlap_candidates(
    db: AsyncSession,
    item_type: str,
    seed_item_ids: list[int],
    excluded_item_ids: set[int],
    limit: int,
) -> list[Any]:
    """Local candidates that share a genre with the seeds, best overlap first.

    Heuristic used for books/games (no external similar API) and as the local
    candidate pool for movies/series before any external fan-out. Ranks by the
    number of shared genres, then external rating. Excludes the seeds
    themselves and anything already seen.
    """
    if not seed_item_ids:
        return []

    model, join, item_col, release_attr = _TYPE_CONFIG[item_type]
    join_item = join.c[item_col]
    release_col = getattr(model, release_attr)

    seed_genre_ids = select(join.c.genre_id).where(join_item.in_(seed_item_ids)).scalar_subquery()

    excluded = set(excluded_item_ids) | set(seed_item_ids)

    overlap = func.count(join.c.genre_id).label("overlap")
    stmt = (
        select(
            model.title.label("title"),
            model.slug.label("slug"),
            model.poster_url.label("poster_url"),
            release_col.label("release_date"),
            model.rating_external.label("rating_external"),
            model.rating_internal.label("rating_internal"),
            overlap,
        )
        .join(join, join_item == model.id)
        .where(join.c.genre_id.in_(seed_genre_ids))
        .where(model.id.notin_(excluded) if excluded else literal(True))
        .group_by(model.id)
        .order_by(overlap.desc(), model.rating_external.desc().nulls_last())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.all())


async def get_popular_items(
    db: AsyncSession,
    item_types: list[str],
    excluded_item_ids: set[tuple[str, int]],
    limit: int,
) -> list[Any]:
    """Cross-type popular fallback: highest community (internal) rating first.

    Used when the user has no seeds. Excludes items the user has already
    seen. ``rating_internal`` decides the order (feature 66 — the
    community's own rating); ``rating_external`` is only an internal
    tie-break for items whose ``rating_internal`` is still NULL or tied.
    The pre-existing ``rating_external IS NOT NULL`` filter is unchanged —
    it still requires *some* rating signal to qualify as "popular" among
    items with no ratings at all yet, it does not decide the order.
    Returns rows with
    item_type/title/slug/poster_url/release_date/rating_external.
    """
    queries = []
    for item_type in item_types:
        model, _join, _item_col, _release_attr = _TYPE_CONFIG[item_type]
        release_col = _release_col(item_type)
        excluded_ids = [iid for (it, iid) in excluded_item_ids if it == item_type]
        q = select(
            literal(item_type, type_=String).label("item_type"),
            model.title.label("title"),
            model.slug.label("slug"),
            model.poster_url.label("poster_url"),
            release_col.label("release_date"),
            model.rating_internal.label("rating_internal"),
            model.rating_external.label("rating_external"),
        ).where(model.rating_external.is_not(None))
        if excluded_ids:
            q = q.where(model.id.notin_(excluded_ids))
        queries.append(q)

    combined = union_all(*queries) if len(queries) > 1 else queries[0]
    subq = combined.subquery()
    stmt = (
        select(subq)
        .order_by(
            subq.c.rating_internal.desc().nulls_last(),
            subq.c.rating_external.desc().nulls_last(),
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.all())


async def get_authorship_works(
    db: AsyncSession,
    person_id: int,
    *,
    exclude: tuple[str, int] | None = None,
    limit: int | None = None,
) -> list[Any]:
    """Return every catalog work this person authored, across all item types.

    Layer 0 of ``docs/recommendations-plan.md``: ``AUTHOR`` (books) and
    ``SOURCE_AUTHOR`` (the film/series adapted from a prior work) are treated
    as **one** authorship class — ``AUTHORSHIP_ROLES`` — so one call from
    either shore returns the other. ``WRITER`` is not authorship and never
    appears here.

    The anti-translator gate: TMDB credits translators with ``job: "Book"``
    (*The Witcher* credits Danusia Stok and David French alongside Sapkowski)
    and the job does not tell them apart, so the whole result is conditioned on
    the person also holding an ``AUTHOR`` credit on a book **that exists in the
    catalog**. A translator has ``SOURCE_AUTHOR`` credits and no book of their
    own, so they get an empty list instead of a bogus bridge.

    ``exclude`` drops the ``(item_type, item_id)`` the caller started from.
    Rows carry item_type/item_id/title/slug/role, ordered by type then id.
    Every item type is covered; ``GAME`` contributes nothing because games
    carry no person credits at all (decision of 2026-09-04, docs/schema.md).
    """
    # Gate, evaluated once for the whole statement: does this person have an
    # AUTHOR credit on a book in the catalog?
    authored_a_book = (
        select(Credit.id)
        .join(Book, Book.id == Credit.item_id)
        .where(
            Credit.person_id == person_id,
            Credit.item_type == "BOOK",
            Credit.role == "AUTHOR",
        )
        .exists()
    )

    queries = []
    for item_type, (model, _join, _item_col, _release_attr) in _TYPE_CONFIG.items():
        q = (
            select(
                literal(item_type, type_=String).label("item_type"),
                model.id.label("item_id"),
                model.title.label("title"),
                model.slug.label("slug"),
                Credit.role.label("role"),
            )
            .select_from(model)
            .join(Credit, and_(Credit.item_id == model.id, Credit.item_type == item_type))
            .where(Credit.person_id == person_id, Credit.role.in_(AUTHORSHIP_ROLES))
        )
        if exclude is not None and exclude[0] == item_type:
            q = q.where(model.id != exclude[1])
        queries.append(q)

    subq = union_all(*queries).subquery()
    stmt = select(subq).where(authored_a_book).order_by(subq.c.item_type, subq.c.item_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.all())
