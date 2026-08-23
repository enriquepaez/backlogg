"""Notifications service — business logic for the notifications feed.

Two responsibilities:

1. Generation helpers (``notify_new_follower`` / ``notify_review_like`` /
   ``notify_user_completed_fanout``) called as a side effect from the
   follows/ratings/library services. These are designed for **graceful
   degradation**: the source operation (the follow / the like / the
   status_completed transition) is already committed by its own service
   before these run, and any failure here is swallowed (logged + rolled back)
   so it can never break that source operation.

2. Read-side operations for the authenticated user: list, unread_count, mark_read.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.notifications import repository as repo
from backlogg.notifications.schemas import (
    NotificationActorOut,
    NotificationListOut,
    NotificationOut,
    NotificationTargetOut,
    UnreadCountOut,
)
from backlogg.users.models import User

logger = logging.getLogger(__name__)


# ── Generation (side effects, must never break the source operation) ─────────


async def notify_new_follower(db: AsyncSession, *, recipient_id: int, actor_id: int) -> None:
    """Create a ``new_follower`` notification for ``recipient_id``.

    Called after the follow has been committed. Swallows any error so a
    notification failure never propagates back to the follow endpoint.
    """
    try:
        await repo.create_notification(
            db,
            recipient_id=recipient_id,
            actor_id=actor_id,
            type="new_follower",
            target_type=None,
            target_id=None,
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to create new_follower notification")
        await db.rollback()


async def notify_review_like(
    db: AsyncSession, *, recipient_id: int, actor_id: int, rating_id: int
) -> None:
    """Create a ``review_like`` notification for the review's author.

    Called after the like has been committed. Swallows any error so a
    notification failure never propagates back to the like endpoint.
    """
    try:
        await repo.create_notification(
            db,
            recipient_id=recipient_id,
            actor_id=actor_id,
            type="review_like",
            target_type="review",
            target_id=rating_id,
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to create review_like notification")
        await db.rollback()


async def notify_user_completed_fanout(
    db: AsyncSession, *, actor_id: int, item_type: str, item_id: int
) -> None:
    """Fan out a ``user_completed`` notification to every direct follower of ``actor_id``.

    Called after the ``status_completed`` feed event (feature 54) has been
    committed by ``backlogg.library.service.set_library_status``.
    ``target_type``/``target_id`` reference the completed item directly (no
    rating involved, unlike ``review_like``). A single batched ``INSERT ...
    SELECT`` (feature 57) replaces what used to be one INSERT+commit per
    follower — on Render's free tier (shared CPU, cold starts) that N-query
    loop could turn a "mark as completed" into a slow request or a timeout
    for users with many followers. Swallows any error so a notification
    failure never propagates back to the ``PUT .../library`` endpoint.
    """
    try:
        await repo.create_user_completed_notifications_for_followers(
            db, actor_id=actor_id, item_type=item_type, item_id=item_id
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to fan out user_completed notifications")
        await db.rollback()


# ── Read side (authenticated user) ───────────────────────────────────────────


def _row_to_out(row) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        type=row.type,
        actor=NotificationActorOut(
            username=row.username,
            display_name=row.display_name,
            avatar_url=row.avatar_url,
        ),
        target=NotificationTargetOut(
            target_type=row.target_type,
            target_id=row.target_id,
            item_type=row.resolved_item_type,
            slug=row.resolved_slug,
        ),
        is_read=row.is_read,
        created_at=row.created_at,
    )


async def list_notifications(
    db: AsyncSession, user: User, page: int, limit: int
) -> NotificationListOut:
    """Paginated, reverse-chronological notifications for the authenticated user."""
    rows, total = await repo.list_notifications(db, user.id, page, limit)
    items = [_row_to_out(row) for row in rows]
    return NotificationListOut(items=items, total=total, page=page, limit=limit)


async def unread_count(db: AsyncSession, user: User) -> UnreadCountOut:
    """Number of unread notifications for the authenticated user."""
    count = await repo.count_unread(db, user.id)
    return UnreadCountOut(unread_count=count)


async def mark_read(db: AsyncSession, user: User, ids: list[int] | None) -> None:
    """Mark the user's notifications as read — all, or only ``ids``. Idempotent."""
    await repo.mark_read(db, user.id, ids)
    await db.commit()


async def delete_notification(db: AsyncSession, user: User, notification_id: int) -> bool:
    """Delete one of the user's own notifications. Returns whether it was deleted."""
    deleted = await repo.delete_notification(db, user.id, notification_id)
    if deleted:
        await db.commit()
    return deleted
