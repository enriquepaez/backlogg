from datetime import datetime

from pydantic import BaseModel


class NotificationActorOut(BaseModel):
    """The user who triggered the notification."""

    username: str
    display_name: str | None
    avatar_url: str | None


class NotificationTargetOut(BaseModel):
    """Polymorphic target of the notification (null for new_follower)."""

    target_type: str | None
    target_id: int | None


class NotificationOut(BaseModel):
    id: int
    type: str
    actor: NotificationActorOut
    target: NotificationTargetOut
    is_read: bool
    created_at: datetime


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    page: int
    limit: int


class UnreadCountOut(BaseModel):
    unread_count: int


class MarkReadIn(BaseModel):
    """Body for POST /notifications/read.

    ``ids`` omitted / null → mark all unread as read. ``ids`` provided → mark
    only those (idempotent).
    """

    ids: list[int] | None = None
