"""Ratings repository — DB queries for user_ratings / review_likes.

Only this file imports and uses SQLAlchemy for the ratings domain. It also
writes directly to the movies/series/books/games tables to recalculate
``rating_internal``/``rating_count_internal`` — same cross-domain write
precedent as ``backlogg/admin/repository.py``.
"""

from typing import Any

from sqlalchemy import String, exists, func, literal, select, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from backlogg.books.models import Book
from backlogg.games.models import Game
from backlogg.movies.models import Movie
from backlogg.ratings.models import ReviewLike, UserRating
from backlogg.series.models import Series
from backlogg.users.models import User

# item_type (as stored on UserRating/credits/external_ids) -> content model
ITEM_MODELS: dict[str, type[DeclarativeBase]] = {
    "MOVIE": Movie,
    "SERIES": Series,
    "BOOK": Book,
    "GAME": Game,
}


def visible_review_filters() -> tuple:
    """Conditions that make a review publicly visible (content moderation).

    A review is visible only when it is **not hidden** by per-review moderation
    (``UserRating.is_hidden = false``) **and** its author is **not banned**
    (``User.is_banned = false``). This single condition is reused across every
    surface that lists reviews or aggregates them (public ratings list, the
    per-user reviews list, the feed and ``recalculate_item_aggregates``) so
    hidden reviews and banned users disappear from all of them consistently.

    Any query using these filters must JOIN ``User`` on ``UserRating.user_id``.
    """
    return (UserRating.is_hidden.is_(False), User.is_banned.is_(False))


async def get_item_by_slug(db: AsyncSession, item_type: str, slug: str) -> Any | None:
    """Look up a content item (Movie/Series/Book/Game) by slug for item_type."""
    model = ITEM_MODELS[item_type]
    result = await db.execute(select(model).where(model.slug == slug))
    return result.scalar_one_or_none()


async def get_rating(
    db: AsyncSession, user_id: int, item_type: str, item_id: int
) -> UserRating | None:
    result = await db.execute(
        select(UserRating).where(
            UserRating.user_id == user_id,
            UserRating.item_type == item_type,
            UserRating.item_id == item_id,
        )
    )
    return result.scalar_one_or_none()


async def get_rating_by_id(db: AsyncSession, rating_id: int) -> UserRating | None:
    result = await db.execute(select(UserRating).where(UserRating.id == rating_id))
    return result.scalar_one_or_none()


async def upsert_rating(
    db: AsyncSession,
    user_id: int,
    item_type: str,
    item_id: int,
    score: float | None,
    review_text: str | None,
) -> UserRating:
    """Insert or update the (user, item) rating. Full replace of score/review_text."""
    stmt = (
        pg_insert(UserRating)
        .values(
            user_id=user_id,
            item_type=item_type,
            item_id=item_id,
            score=score,
            review_text=review_text,
        )
        .on_conflict_do_update(
            constraint="uq_user_rating_item",
            set_={"score": score, "review_text": review_text},
        )
        .returning(UserRating.id)
    )
    result = await db.execute(stmt)
    rating_id = result.scalar_one()
    await db.flush()

    # Expire any cached version so the SELECT below returns the fresh row,
    # not a stale identity-map entry (same pattern as movies.upsert_movie).
    for obj in db.identity_map.values():
        if isinstance(obj, UserRating) and obj.id == rating_id:
            db.expire(obj)
            break

    row = await db.execute(select(UserRating).where(UserRating.id == rating_id))
    return row.scalar_one()


async def delete_rating(db: AsyncSession, rating: UserRating) -> None:
    await db.delete(rating)
    await db.flush()


async def set_rating_hidden(db: AsyncSession, rating: UserRating, hidden: bool) -> UserRating:
    """Set a review's moderation flag. Idempotent — no-op if already in that state.

    The caller (moderation service) recomputes the affected item's aggregates
    afterwards so a newly hidden/unhidden review is reflected in the average.
    """
    if rating.is_hidden != hidden:
        rating.is_hidden = hidden
        await db.flush()
    return rating


async def get_distinct_rated_items_for_user(
    db: AsyncSession, user_id: int
) -> list[tuple[str, int]]:
    """Return the distinct ``(item_type, item_id)`` a user has rated.

    Used before deleting an account: the DB ``ON DELETE CASCADE`` removes the
    user's ``user_ratings`` rows but does not recompute the affected items'
    aggregates, so the caller must recalculate each of these items afterwards.
    """
    result = await db.execute(
        select(UserRating.item_type, UserRating.item_id)
        .where(UserRating.user_id == user_id)
        .distinct()
    )
    return [(row[0], row[1]) for row in result.all()]


async def recalculate_item_aggregates(db: AsyncSession, item_type: str, item_id: int) -> None:
    """Recompute rating_internal (AVG) / rating_count_internal (COUNT) for an item.

    Ignores ratings with a NULL score (text-only reviews don't count toward
    the average) and, per content moderation, any review that is not visible —
    hidden reviews and reviews authored by a banned user (``visible_review_filters``,
    which is why the query JOINs ``users``). Persists directly on the
    movies/series/books/games row.
    """
    model = ITEM_MODELS[item_type]
    agg_result = await db.execute(
        select(func.avg(UserRating.score), func.count(UserRating.score))
        .join(User, UserRating.user_id == User.id)
        .where(
            UserRating.item_type == item_type,
            UserRating.item_id == item_id,
            UserRating.score.is_not(None),
            *visible_review_filters(),
        )
    )
    avg_score, count_score = agg_result.one()

    item = await db.get(model, item_id)
    if item is None:
        return

    item.rating_internal = round(avg_score, 2) if avg_score is not None else None
    item.rating_count_internal = count_score or 0
    await db.flush()


async def recalculate_item_aggregates_batch(db: AsyncSession, items: list[tuple[str, int]]) -> None:
    """Batched version of ``recalculate_item_aggregates`` for many items at once.

    Same semantics (average/count over visible, scored ratings only — see
    ``visible_review_filters``) but a constant number of queries instead of a
    SELECT+write per item: at most two ``UPDATE`` statements per distinct
    ``item_type`` present in ``items`` (feature 62 — used by ``set_user_banned``
    and ``delete_current_user``, where a single user action can affect many
    items at once).

    For each content type:
    1. Every affected item is first reset to ``(rating_internal=None,
       rating_count_internal=0)``. This is needed because an item that ends up
       with zero visible scored ratings (e.g. its only rating just got hidden
       by a ban) would otherwise be skipped entirely by the aggregate query
       below, which only ever touches item ids that still have at least one
       matching row.
    2. A single ``UPDATE ... FROM`` against a ``GROUP BY item_id`` aggregate
       subquery overwrites the reset value for items that still have visible
       scored ratings.
    """
    if not items:
        return

    ids_by_type: dict[str, list[int]] = {}
    for item_type, item_id in items:
        ids_by_type.setdefault(item_type, []).append(item_id)

    for item_type, item_ids in ids_by_type.items():
        model = ITEM_MODELS[item_type]

        await db.execute(
            update(model)
            .where(model.id.in_(item_ids))
            .values(rating_internal=None, rating_count_internal=0)
        )

        agg_subq = (
            select(
                UserRating.item_id.label("item_id"),
                func.avg(UserRating.score).label("avg_score"),
                func.count(UserRating.score).label("count_score"),
            )
            .join(User, UserRating.user_id == User.id)
            .where(
                UserRating.item_type == item_type,
                UserRating.item_id.in_(item_ids),
                UserRating.score.is_not(None),
                *visible_review_filters(),
            )
            .group_by(UserRating.item_id)
            .subquery()
        )

        await db.execute(
            update(model)
            .where(model.id == agg_subq.c.item_id)
            .values(
                rating_internal=func.round(agg_subq.c.avg_score, 2),
                rating_count_internal=agg_subq.c.count_score,
            )
        )

    await db.flush()


async def list_ratings_for_item(
    db: AsyncSession,
    item_type: str,
    item_id: int,
    page: int,
    limit: int,
    caller_id: int | None = None,
) -> tuple[list[Any], int]:
    """Return paginated (UserRating, User, like_count, liked_by_viewer) rows for an item.

    Newest first.

    ``caller_id`` is the authenticated viewer's id (``None`` for an anonymous
    caller). When present, ``liked_by_viewer`` is a correlated ``EXISTS`` over
    ``ReviewLike`` scoped to that user — same single-query, no-N+1 pattern as
    ``like_count_subq``. When ``caller_id is None`` there is no DB round trip
    needed to know an anonymous caller never liked anything, so the column is
    a plain ``literal(False)`` instead.
    """
    like_count_subq = (
        select(func.count())
        .select_from(ReviewLike)
        .where(ReviewLike.rating_id == UserRating.id)
        .correlate(UserRating)
        .scalar_subquery()
    )

    if caller_id is not None:
        liked_by_viewer_expr = exists(
            select(1)
            .select_from(ReviewLike)
            .where(ReviewLike.rating_id == UserRating.id, ReviewLike.user_id == caller_id)
            .correlate(UserRating)
        )
    else:
        liked_by_viewer_expr = literal(False)

    count_result = await db.execute(
        select(func.count())
        .select_from(UserRating)
        .join(User, UserRating.user_id == User.id)
        .where(
            UserRating.item_type == item_type,
            UserRating.item_id == item_id,
            *visible_review_filters(),
        )
    )
    total = count_result.scalar_one()

    paged_stmt = (
        select(
            UserRating,
            User,
            like_count_subq.label("like_count"),
            liked_by_viewer_expr.label("liked_by_viewer"),
        )
        .join(User, UserRating.user_id == User.id)
        .where(
            UserRating.item_type == item_type,
            UserRating.item_id == item_id,
            *visible_review_filters(),
        )
        .order_by(UserRating.created_at.desc(), UserRating.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.all()), total


async def list_user_reviews(
    db: AsyncSession, user_id: int, page: int, limit: int
) -> tuple[list[Any], int]:
    """Cross-type UNION ALL of a user's ratings/reviews, newest first.

    Same style as backlogg/genres/repository.py and
    backlogg/search/repository.py — one SELECT per item type joined to its
    content table, combined with union_all.
    """
    queries = []
    for item_type, model in ITEM_MODELS.items():
        q = (
            select(
                UserRating.id.label("id"),
                literal(item_type, type_=String).label("item_type"),
                model.title.label("title"),
                model.slug.label("slug"),
                model.poster_url.label("poster_url"),
                UserRating.score.label("score"),
                UserRating.review_text.label("review_text"),
                UserRating.created_at.label("created_at"),
                UserRating.updated_at.label("updated_at"),
            )
            .join(model, UserRating.item_id == model.id)
            .join(User, UserRating.user_id == User.id)
            .where(
                UserRating.user_id == user_id,
                UserRating.item_type == item_type,
                *visible_review_filters(),
            )
        )
        queries.append(q)

    union_subq = union_all(*queries).subquery()

    count_result = await db.execute(select(func.count()).select_from(union_subq))
    total = count_result.scalar_one()

    paged_stmt = (
        select(union_subq)
        .order_by(union_subq.c.created_at.desc(), union_subq.c.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.all()), total


async def get_like(db: AsyncSession, user_id: int, rating_id: int) -> ReviewLike | None:
    result = await db.execute(
        select(ReviewLike).where(ReviewLike.user_id == user_id, ReviewLike.rating_id == rating_id)
    )
    return result.scalar_one_or_none()


async def create_like_if_not_exists(db: AsyncSession, user_id: int, rating_id: int) -> bool:
    """Idempotent like — INSERT ... ON CONFLICT DO NOTHING.

    Returns ``True`` when a new like row was inserted, ``False`` when the like
    already existed (idempotent no-op). ``RETURNING id`` yields no rows on
    conflict, so callers can tell whether to fire a ``review_like``
    notification for the review's author.
    """
    stmt = (
        pg_insert(ReviewLike)
        .values(user_id=user_id, rating_id=rating_id)
        .on_conflict_do_nothing(constraint="uq_review_like")
        .returning(ReviewLike.id)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.scalar_one_or_none() is not None


async def delete_like_if_exists(db: AsyncSession, user_id: int, rating_id: int) -> None:
    """Idempotent unlike — no-op if the like doesn't exist."""
    like = await get_like(db, user_id, rating_id)
    if like is not None:
        await db.delete(like)
        await db.flush()


async def count_likes(db: AsyncSession, rating_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(ReviewLike).where(ReviewLike.rating_id == rating_id)
    )
    return result.scalar_one()
