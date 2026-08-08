"""Follows repository — DB queries for the follows table.

Only this file imports and uses SQLAlchemy for the follows domain. Reused by
``backlogg/users/service.py`` to enrich the public profile with
``follower_count``/``following_count``.
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.follows.models import Follow
from backlogg.users.models import User


async def create_follow_if_not_exists(db: AsyncSession, follower_id: int, followed_id: int) -> bool:
    """Idempotent follow — INSERT ... ON CONFLICT DO NOTHING.

    Returns ``True`` when a new row was actually inserted, ``False`` when the
    follow already existed (idempotent no-op). ``RETURNING id`` yields no rows
    on conflict, so callers can tell whether to fire a side effect such as a
    ``new_follower`` notification.
    """
    stmt = (
        pg_insert(Follow)
        .values(follower_id=follower_id, followed_id=followed_id)
        .on_conflict_do_nothing(constraint="uq_follow_pair")
        .returning(Follow.id)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.scalar_one_or_none() is not None


async def delete_follow_if_exists(db: AsyncSession, follower_id: int, followed_id: int) -> None:
    """Idempotent unfollow — no-op if the relationship doesn't exist."""
    result = await db.execute(
        select(Follow).where(Follow.follower_id == follower_id, Follow.followed_id == followed_id)
    )
    follow = result.scalar_one_or_none()
    if follow is not None:
        await db.delete(follow)
        await db.flush()


async def count_followers(db: AsyncSession, user_id: int) -> int:
    """How many users follow ``user_id``."""
    result = await db.execute(
        select(func.count()).select_from(Follow).where(Follow.followed_id == user_id)
    )
    return result.scalar_one()


async def count_following(db: AsyncSession, user_id: int) -> int:
    """How many users ``user_id`` follows."""
    result = await db.execute(
        select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
    )
    return result.scalar_one()


async def list_followers(
    db: AsyncSession, user_id: int, page: int, limit: int
) -> tuple[list[User], int]:
    """Paginated list of users who follow ``user_id``, most recent first."""
    count_result = await db.execute(
        select(func.count()).select_from(Follow).where(Follow.followed_id == user_id)
    )
    total = count_result.scalar_one()

    paged_stmt = (
        select(User)
        .join(Follow, Follow.follower_id == User.id)
        .where(Follow.followed_id == user_id)
        .order_by(Follow.created_at.desc(), Follow.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.scalars().all()), total


async def list_following(
    db: AsyncSession, user_id: int, page: int, limit: int
) -> tuple[list[User], int]:
    """Paginated list of users that ``user_id`` follows, most recent first."""
    count_result = await db.execute(
        select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
    )
    total = count_result.scalar_one()

    paged_stmt = (
        select(User)
        .join(Follow, Follow.followed_id == User.id)
        .where(Follow.follower_id == user_id)
        .order_by(Follow.created_at.desc(), Follow.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.scalars().all()), total
