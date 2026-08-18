"""Ratings service — business logic for ratings/reviews across all 4 content types.

Each PUT/DELETE/GET .../rating(s) route in movies/series/books/games routes.py
delegates here, passing the resolved ``item_type`` ("MOVIE"/"SERIES"/"BOOK"/
"GAME") and the ``slug`` from the URL. This keeps the upsert + aggregate
recalculation logic in one place instead of duplicating it across four
domain slices.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.feed import repository as feed_repo
from backlogg.notifications import service as notifications_service
from backlogg.ratings import repository as repo
from backlogg.ratings.schemas import (
    RatingAuthorOut,
    RatingIn,
    RatingListOut,
    RatingOut,
    UserReviewItemOut,
    UserReviewListOut,
    UserReviewOut,
)
from backlogg.users import repository as users_repo
from backlogg.users.models import User

_ITEM_NOT_FOUND_DETAIL = {
    "MOVIE": "Movie not found",
    "SERIES": "Series not found",
    "BOOK": "Book not found",
    "GAME": "Game not found",
}


def _rating_to_out(rating, user: User, like_count: int, liked_by_viewer: bool = False) -> RatingOut:
    return RatingOut(
        id=rating.id,
        user=RatingAuthorOut.model_validate(user),
        score=rating.score,
        review_text=rating.review_text,
        like_count=like_count,
        liked_by_viewer=liked_by_viewer,
        created_at=rating.created_at,
        updated_at=rating.updated_at,
    )


async def _get_item_or_404(db: AsyncSession, item_type: str, slug: str):
    item = await repo.get_item_by_slug(db, item_type, slug)
    if item is None:
        raise HTTPException(status_code=404, detail=_ITEM_NOT_FOUND_DETAIL[item_type])
    return item


async def rate_item(
    db: AsyncSession, item_type: str, slug: str, payload: RatingIn, user: User
) -> RatingOut:
    """Upsert the authenticated user's score/review_text for an item."""
    item = await _get_item_or_404(db, item_type, slug)

    rating = await repo.upsert_rating(
        db,
        user_id=user.id,
        item_type=item_type,
        item_id=item.id,
        score=payload.score,
        review_text=payload.review_text,
    )
    await repo.recalculate_item_aggregates(db, item_type, item.id)

    # Feed event generation (feature 54): a rating with actual content
    # (score and/or review_text) gets a rating_created event — inserted once
    # and left alone on later updates to the same rating (ON CONFLICT DO
    # NOTHING keyed on rating_id, so no duplicates). If an update clears both
    # fields back to null, the event is removed — a contentless rating has
    # nothing worth surfacing in the feed. This runs in the same transaction
    # as the rating write (unlike the notifications side effects elsewhere in
    # this codebase, which commit separately for graceful degradation): it's
    # a plain local insert/delete with no external call, so keeping it atomic
    # with the rating avoids ever having a rating without its event or vice
    # versa.
    if rating.score is not None or rating.review_text is not None:
        await feed_repo.create_rating_event(
            db, user_id=user.id, item_type=item_type, item_id=item.id, rating_id=rating.id
        )
    else:
        await feed_repo.delete_rating_event(db, rating.id)

    await db.commit()

    like_count = await repo.count_likes(db, rating.id)
    return _rating_to_out(rating, user, like_count)


async def delete_item_rating(db: AsyncSession, item_type: str, slug: str, user: User) -> None:
    """Delete the authenticated user's own rating for an item. 404 if it doesn't exist."""
    item = await _get_item_or_404(db, item_type, slug)

    rating = await repo.get_rating(db, user_id=user.id, item_type=item_type, item_id=item.id)
    if rating is None:
        raise HTTPException(status_code=404, detail="Rating not found")

    await repo.delete_rating(db, rating)
    await repo.recalculate_item_aggregates(db, item_type, item.id)
    await db.commit()


async def list_item_ratings(
    db: AsyncSession,
    item_type: str,
    slug: str,
    page: int,
    limit: int,
    caller_id: int | None = None,
) -> RatingListOut:
    """Public, paginated list of ratings/reviews for an item, newest first.

    ``caller_id`` is the authenticated viewer's id, if any (``None`` for an
    anonymous caller) — resolves each review's ``liked_by_viewer`` for that
    specific caller. The endpoint itself stays public either way.
    """
    item = await _get_item_or_404(db, item_type, slug)

    rows, total = await repo.list_ratings_for_item(
        db, item_type, item.id, page, limit, caller_id=caller_id
    )
    items = [
        _rating_to_out(rating, user, like_count, liked_by_viewer)
        for rating, user, like_count, liked_by_viewer in rows
    ]
    return RatingListOut(items=items, total=total, page=page, limit=limit)


async def like_review(db: AsyncSession, rating_id: int, user: User) -> None:
    """Like a review. Idempotent — liking twice does not duplicate. 404 if rating missing."""
    rating = await repo.get_rating_by_id(db, rating_id)
    if rating is None:
        raise HTTPException(status_code=404, detail="Rating not found")

    created = await repo.create_like_if_not_exists(db, user_id=user.id, rating_id=rating_id)
    await db.commit()

    # Notify the review's author — only on a genuinely new like, and never when
    # a user likes their own review. Runs after the like is committed and cannot
    # break it (graceful degradation).
    if created and rating.user_id != user.id:
        await notifications_service.notify_review_like(
            db, recipient_id=rating.user_id, actor_id=user.id, rating_id=rating_id
        )


async def unlike_review(db: AsyncSession, rating_id: int, user: User) -> None:
    """Unlike a review. Idempotent — unliking twice (or never liked) is a no-op."""
    rating = await repo.get_rating_by_id(db, rating_id)
    if rating is None:
        raise HTTPException(status_code=404, detail="Rating not found")

    await repo.delete_like_if_exists(db, user_id=user.id, rating_id=rating_id)
    await db.commit()


async def get_user_reviews(
    db: AsyncSession, username: str, page: int, limit: int
) -> UserReviewListOut:
    """Public, cross-type (UNION ALL) list of a user's ratings/reviews, newest first."""
    target_user = await users_repo.get_user_by_username(db, username)
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    rows, total = await repo.list_user_reviews(db, target_user.id, page, limit)
    items = [
        UserReviewOut(
            id=row.id,
            item=UserReviewItemOut(
                item_type=row.item_type,
                title=row.title,
                slug=row.slug,
                poster_url=row.poster_url,
            ),
            score=row.score,
            review_text=row.review_text,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return UserReviewListOut(items=items, total=total, page=page, limit=limit)
