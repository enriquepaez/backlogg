"""Moderation service — admin actions that hide reviews and ban users.

Moderation is a thin orchestration slice: it owns no table of its own but flips
the ``UserRating.is_hidden`` / ``User.is_banned`` flags (via the ratings/users
repositories that own those tables) and then recomputes the affected catalog
aggregates. The "visible review" condition — not hidden **and** author not
banned — lives in ``ratings.repository.visible_review_filters`` and is applied
consistently by ``recalculate_item_aggregates`` and every review listing.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.moderation.schemas import ReviewModerationOut, UserModerationOut
from backlogg.ratings import repository as ratings_repo
from backlogg.users import repository as users_repo


async def set_review_hidden(db: AsyncSession, rating_id: int, hidden: bool) -> ReviewModerationOut:
    """Hide or unhide a single review and recompute its item's aggregates.

    Raises 404 if the review does not exist. Idempotent: hiding an already
    hidden review (or unhiding a visible one) is a no-op that still returns the
    review's current state. The aggregate recompute after the flag change
    excludes/includes the review from ``rating_internal``/``rating_count_internal``.
    """
    rating = await ratings_repo.get_rating_by_id(db, rating_id)
    if rating is None:
        raise HTTPException(status_code=404, detail="Review not found")

    await ratings_repo.set_rating_hidden(db, rating, hidden)
    await ratings_repo.recalculate_item_aggregates(db, rating.item_type, rating.item_id)
    await db.commit()
    return ReviewModerationOut(id=rating.id, is_hidden=hidden)


async def set_user_banned(db: AsyncSession, username: str, banned: bool) -> UserModerationOut:
    """Ban or unban a user and recompute the aggregates of every item they rated.

    Raises 404 if the user does not exist. Idempotent. Banning flips every one
    of the user's reviews to invisible (and unbanning back to visible), which
    changes the average of every item they had rated — so the affected items are
    captured first (``get_distinct_rated_items_for_user``, reused from account
    deletion) and recomputed after the flag flips. The flag change plus all
    recomputes commit atomically, mirroring the account-deletion flow.
    """
    user = await users_repo.get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    rated_items = await ratings_repo.get_distinct_rated_items_for_user(db, user.id)
    await users_repo.set_user_banned(db, user, banned)
    for item_type, item_id in rated_items:
        await ratings_repo.recalculate_item_aggregates(db, item_type, item_id)
    await db.commit()
    return UserModerationOut(username=user.username, is_banned=banned)
