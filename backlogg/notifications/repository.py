"""Notifications repository — DB queries for the notifications table.

Only this file imports and uses SQLAlchemy for the notifications domain. The
list query joins the actor (users) so the actor's public fields
(username/display_name/avatar_url) are resolved in one round-trip, avoiding
N+1. It also resolves the target item in the same query, for both flavors of
polymorphic target the table holds:

- ``review_like`` (``target_type='review'``): LEFT JOIN to ``user_ratings`` on
  the notification's target, then one conditional LEFT JOIN per content model
  (reusing ``ITEM_MODELS`` from ``backlogg.ratings.repository``) matched on
  ``user_ratings.item_type``/``item_id``.
- ``user_completed`` (``target_type`` = the item's ``item_type`` uppercase):
  the same per-content-model LEFT JOINs are reused, this time matched
  directly on ``notifications.target_type``/``target_id`` — no
  ``user_ratings`` hop, since there is no rating involved.

Both flavors share the same four LEFT JOINs (one per content model) instead
of duplicating the whole query — each join's ON clause simply ORs the two
match conditions, so ``slug``/``item_type`` COALESCE out in a single
round-trip regardless of which target flavor or item type is involved.
"""

from typing import Any

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.notifications.models import Notification
from backlogg.ratings.models import UserRating
from backlogg.ratings.repository import ITEM_MODELS
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

    # resolved_item_type: for review_like it's the rating's item_type (only
    # known once user_ratings is joined); for user_completed (and any future
    # type whose target_type is directly one of the four content types) it's
    # the notification's own target_type — no user_ratings hop needed.
    resolved_item_type_expr = case(
        (UserRating.item_type.is_not(None), UserRating.item_type),
        (Notification.target_type.in_(ITEM_MODELS.keys()), Notification.target_type),
    ).label("resolved_item_type")

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
            resolved_item_type_expr,
            func.coalesce(*(model.slug for model in ITEM_MODELS.values())).label("resolved_slug"),
        )
        .join(User, Notification.actor_id == User.id)
        .outerjoin(
            UserRating,
            (Notification.target_type == "review") & (Notification.target_id == UserRating.id),
        )
    )
    for item_type, model in ITEM_MODELS.items():
        paged_stmt = paged_stmt.outerjoin(
            model,
            ((UserRating.item_type == item_type) & (UserRating.item_id == model.id))
            | ((Notification.target_type == item_type) & (Notification.target_id == model.id)),
        )
    paged_stmt = (
        paged_stmt.where(Notification.recipient_id == recipient_id)
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


async def delete_notification(db: AsyncSession, recipient_id: int, notification_id: int) -> bool:
    """Delete one notification, scoped to ``recipient_id``. Returns whether a row was deleted.

    Scoping the WHERE clause to ``recipient_id`` means the caller can never
    delete someone else's notification — a mismatched id simply deletes
    nothing, and the service maps that to a 404 without distinguishing
    "doesn't exist" from "isn't yours".
    """
    stmt = delete(Notification).where(
        Notification.id == notification_id,
        Notification.recipient_id == recipient_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0
