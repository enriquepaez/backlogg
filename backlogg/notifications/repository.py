"""Notifications repository — DB queries for the notifications table.

Only this file imports and uses SQLAlchemy for the notifications domain. The
list query joins the actor (users) so the actor's public fields
(username/display_name/avatar_url) are resolved in one round-trip, avoiding N+1.
"""

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.notifications.models import Notification
from backlogg.users.models import User


async def create_notification(
    db: AsyncSession,
    *,
    recipient_id: int,
    actor_id: int,
    type: str,
    target_type: str | None,
    target_id: int | None,
) -> Notification:
    """Insert a notification row and return it."""
    notification = Notification(
        recipient_id=recipient_id,
        actor_id=actor_id,
        type=type,
        target_type=target_type,
        target_id=target_id,
    )
    db.add(notification)
    await db.flush()
    return notification


async def list_notifications(
    db: AsyncSession, recipient_id: int, page: int, limit: int
) -> tuple[list[Any], int]:
    """Paginated notifications for a recipient, newest first, with actor fields."""
    count_result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_id == recipient_id)
    )
    total = count_result.scalar_one()

    paged_stmt = (
        select(
            Notification.id.label("id"),
            Notification.type.label("type"),
            Notification.target_type.label("target_type"),
            Notification.target_id.label("target_id"),
            Notification.is_read.label("is_read"),
            Notification.created_at.label("created_at"),
            User.username.label("username"),
            User.display_name.label("display_name"),
            User.avatar_url.label("avatar_url"),
        )
        .join(User, Notification.actor_id == User.id)
        .where(Notification.recipient_id == recipient_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.all()), total


async def count_unread(db: AsyncSession, recipient_id: int) -> int:
    """How many unread notifications the recipient has."""
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.recipient_id == recipient_id,
            Notification.is_read.is_(False),
        )
    )
    return result.scalar_one()


async def mark_read(db: AsyncSession, recipient_id: int, ids: list[int] | None = None) -> None:
    """Mark the recipient's notifications as read — all of them, or only ``ids``.

    Idempotent: already-read rows are unaffected; unknown ids simply match
    nothing. Scoped to ``recipient_id`` so a caller can never mark someone
    else's notifications.
    """
    stmt = (
        update(Notification)
        .where(
            Notification.recipient_id == recipient_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    await db.execute(stmt)
    await db.flush()
