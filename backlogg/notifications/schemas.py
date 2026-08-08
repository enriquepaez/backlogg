from datetime import datetime

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 91,
                        "type": "review_like",
                        "actor": {
                            "username": "bob",
                            "display_name": "Bob",
                            "avatar_url": "https://cdn.example.com/a/bob.png",
                        },
                        "target": {"target_type": "review", "target_id": 512},
                        "is_read": False,
                        "created_at": "2026-05-25T18:04:11Z",
                    }
                ],
                "total": 5,
                "page": 1,
                "limit": 20,
            }
        }
    )


class UnreadCountOut(BaseModel):
    unread_count: int


class MarkReadIn(BaseModel):
    """Body for POST /notifications/read.

    ``ids`` omitted / null → mark all unread as read. ``ids`` provided → mark
    only those (idempotent).
    """

    ids: list[int] | None = None
