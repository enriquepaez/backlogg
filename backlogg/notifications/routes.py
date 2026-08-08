from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.notifications import service
from backlogg.notifications.schemas import (
    MarkReadIn,
    NotificationListOut,
    UnreadCountOut,
)
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])


@notifications_router.get(
    "",
    response_model=NotificationListOut,
    summary="List notifications",
    description="The caller's notifications, paginated, newest first. Requires auth.",
)
async def list_notifications(
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_notifications(db, user=current_user, page=page, limit=limit)


@notifications_router.get(
    "/unread_count",
    response_model=UnreadCountOut,
    summary="Unread notification count",
    description="Number of unread notifications for the caller. Requires auth.",
)
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.unread_count(db, user=current_user)


@notifications_router.post(
    "/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark notifications read",
    description="Mark notifications read. Empty body marks all, else only given ids. Idempotent.",
)
async def mark_read(
    payload: MarkReadIn | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ids = payload.ids if payload is not None else None
    await service.mark_read(db, user=current_user, ids=ids)
