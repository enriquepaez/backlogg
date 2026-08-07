"""Follows service — business logic for following/unfollowing users.

A follow is unidirectional and needs no approval. Following is idempotent
(following twice is a no-op) and so is unfollowing (unfollowing someone you
don't follow is a no-op). A user cannot follow themselves (422).
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.follows import repository as repo
from backlogg.follows.schemas import FollowListOut, FollowUserOut
from backlogg.users import repository as users_repo
from backlogg.users.models import User


async def _get_target_or_404(db: AsyncSession, username: str) -> User:
    target = await users_repo.get_user_by_username(db, username)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return target


async def follow_user(db: AsyncSession, username: str, user: User) -> None:
    """Follow ``username`` as the authenticated ``user``.

    Idempotent. Raises 404 if the target does not exist, 422 on self-follow.
    """
    target = await _get_target_or_404(db, username)
    if target.id == user.id:
        raise HTTPException(status_code=422, detail="You cannot follow yourself")

    await repo.create_follow_if_not_exists(db, follower_id=user.id, followed_id=target.id)
    await db.commit()


async def unfollow_user(db: AsyncSession, username: str, user: User) -> None:
    """Unfollow ``username`` as the authenticated ``user``.

    Idempotent — a no-op if ``user`` wasn't following ``username``. Raises 404
    if the target does not exist.
    """
    target = await _get_target_or_404(db, username)

    await repo.delete_follow_if_exists(db, follower_id=user.id, followed_id=target.id)
    await db.commit()


async def list_followers(db: AsyncSession, username: str, page: int, limit: int) -> FollowListOut:
    """Public, paginated list of users who follow ``username``."""
    target = await _get_target_or_404(db, username)

    users, total = await repo.list_followers(db, target.id, page, limit)
    items = [FollowUserOut.model_validate(u) for u in users]
    return FollowListOut(items=items, total=total, page=page, limit=limit)


async def list_following(db: AsyncSession, username: str, page: int, limit: int) -> FollowListOut:
    """Public, paginated list of users that ``username`` follows."""
    target = await _get_target_or_404(db, username)

    users, total = await repo.list_following(db, target.id, page, limit)
    items = [FollowUserOut.model_validate(u) for u in users]
    return FollowListOut(items=items, total=total, page=page, limit=limit)
