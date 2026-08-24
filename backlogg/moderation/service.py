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

from backlogg.admin import audit
from backlogg.moderation.schemas import ReviewModerationOut, UserModerationOut
from backlogg.ratings import repository as ratings_repo
from backlogg.users import repository as users_repo


async def set_review_hidden(db: AsyncSession, rating_id: int, hidden: bool) -> ReviewModerationOut:
    """Hide or unhide a single review and recompute its item's aggregates.

    Raises 404 if the review does not exist. Idempotent: hiding an already
    hidden review (or unhiding a visible one) is a no-op that still returns the
    review's current state. The aggregate recompute after the flag change
    excludes/includes the review from ``rating_internal``/``rating_count_internal``.

    Feature 63: records an ``admin_actions`` audit row (``hide_review`` /
    ``unhide_review``) in the same transaction, every call — including
    idempotent repeats, each invocation of this admin action is worth its own
    audit entry. ``actor_id`` is always ``None``: this route is gated solely
    by X-API-Key, with no caller identity to record.
    """
    rating = await ratings_repo.get_rating_by_id(db, rating_id)
    if rating is None:
        raise HTTPException(status_code=404, detail="Review not found")

    await ratings_repo.set_rating_hidden(db, rating, hidden)
    await ratings_repo.recalculate_item_aggregates(db, rating.item_type, rating.item_id)
    await audit.record_admin_action(
        db,
        actor_id=None,
        action=audit.ACTION_HIDE_REVIEW if hidden else audit.ACTION_UNHIDE_REVIEW,
        target_type=audit.TARGET_REVIEW,
        target_id=rating.id,
    )
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

    The recompute is batched (``recalculate_item_aggregates_batch``, feature
    62) into a constant number of queries per content type instead of one
    SELECT+write per item — a user with many ratings would otherwise force N
    sequential round-trips before this could commit.

    Feature 63: records an ``admin_actions`` audit row (``ban_user`` /
    ``unban_user``) in the same transaction, every call — including idempotent
    repeats. ``actor_id`` is always ``None``: this route is gated solely by
    X-API-Key, with no caller identity to record.
    """
    user = await users_repo.get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    rated_items = await ratings_repo.get_distinct_rated_items_for_user(db, user.id)
    await users_repo.set_user_banned(db, user, banned)
    await ratings_repo.recalculate_item_aggregates_batch(db, rated_items)
    await audit.record_admin_action(
        db,
        actor_id=None,
        action=audit.ACTION_BAN_USER if banned else audit.ACTION_UNBAN_USER,
        target_type=audit.TARGET_USER,
        target_id=user.id,
    )
    await db.commit()
    return UserModerationOut(username=user.username, is_banned=banned)
