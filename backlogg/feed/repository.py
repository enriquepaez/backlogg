"""Feed repository — cross-type UNION ALL over user reviews.

Only this file imports and uses SQLAlchemy for the feed domain. It reuses the
``ITEM_MODELS`` mapping from ``backlogg/ratings/repository.py`` and builds the
feed with the same style as ``backlogg/genres/repository.py`` and
``backlogg/ratings/repository.py::list_user_reviews`` — one SELECT per item
type joined to its content table, combined with ``union_all``. No new table
and no materialized view.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.follows.models import Follow
from backlogg.ratings.models import ReviewLike, UserRating
from backlogg.ratings.repository import ITEM_MODELS
from backlogg.users.models import User

POPULAR_WINDOW_DAYS = 30


def _like_count_subquery():
    """Aggregated like counts per rating — LEFT JOINed so ratings with zero
    likes still appear (COALESCE to 0) and popular can order by it robustly."""
    return (
        select(
            ReviewLike.rating_id.label("rating_id"),
            func.count().label("like_count"),
        )
        .group_by(ReviewLike.rating_id)
        .subquery()
    )


def _feed_select(item_type: str, model: type, like_subq):
    """Base SELECT for one item type: review + author (JOIN users) + like_count.

    Author fields are resolved inside the SQL (JOIN to users) to avoid N+1.
    """
    return (
        select(
            UserRating.id.label("id"),
            literal(item_type, type_=String).label("item_type"),
            model.title.label("title"),
            model.slug.label("slug"),
            model.poster_url.label("poster_url"),
            UserRating.score.label("score"),
            UserRating.review_text.label("review_text"),
            UserRating.created_at.label("created_at"),
            User.username.label("username"),
            User.display_name.label("display_name"),
            User.avatar_url.label("avatar_url"),
            func.coalesce(like_subq.c.like_count, 0).label("like_count"),
        )
        .join(model, UserRating.item_id == model.id)
        .join(User, UserRating.user_id == User.id)
        .outerjoin(like_subq, like_subq.c.rating_id == UserRating.id)
    )


async def list_following_feed(
    db: AsyncSession, caller_id: int, page: int, limit: int
) -> tuple[list[Any], int]:
    """Reviews from users the caller follows, newest first, paginated.

    Caller with no follows → empty list (the ``IN (...)`` subquery is simply
    empty, so this is not an error).
    """
    like_subq = _like_count_subquery()
    followed_subq = select(Follow.followed_id).where(Follow.follower_id == caller_id)

    queries = [
        _feed_select(item_type, model, like_subq).where(
            UserRating.item_type == item_type,
            UserRating.user_id.in_(followed_subq),
        )
        for item_type, model in ITEM_MODELS.items()
    ]
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


async def list_popular_feed(db: AsyncSession, page: int, limit: int) -> tuple[list[Any], int]:
    """Reviews from the last 30 days ordered by like_count desc, then newest first."""
    cutoff = datetime.now(UTC) - timedelta(days=POPULAR_WINDOW_DAYS)
    like_subq = _like_count_subquery()

    queries = [
        _feed_select(item_type, model, like_subq).where(
            UserRating.item_type == item_type,
            UserRating.created_at >= cutoff,
        )
        for item_type, model in ITEM_MODELS.items()
    ]
    union_subq = union_all(*queries).subquery()

    count_result = await db.execute(select(func.count()).select_from(union_subq))
    total = count_result.scalar_one()

    paged_stmt = (
        select(union_subq)
        .order_by(
            union_subq.c.like_count.desc(),
            union_subq.c.created_at.desc(),
            union_subq.c.id.desc(),
        )
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.all()), total
