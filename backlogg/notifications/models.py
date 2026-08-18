from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

__all__ = ["Notification", "NOTIFICATION_TYPES"]

# Allowed values for Notification.type. Kept as a plain String + CheckConstraint
# (same style as the polymorphic item_type on UserRating/library_entries) instead
# of a native PG enum, so adding a new type later is a data-only migration.
NOTIFICATION_TYPES = ("new_follower", "review_like", "user_completed")


class Notification(Base):
    """A social notification for a recipient user.

    Generated as a side effect of social events:
    - ``new_follower``: someone followed the recipient (no target).
    - ``review_like``: someone liked one of the recipient's reviews
      (``target_type='review'``, ``target_id`` = the UserRating id).
    - ``user_completed``: a followed user completed an item (feature 54's
      ``status_completed`` feed event), fanned out to each direct follower
      (``target_type`` = the item's ``item_type`` uppercase, ``target_id`` =
      the item id — a direct reference to the content row, unlike
      ``review_like`` there is no rating involved).

    ``actor_id`` is the user who triggered the event; ``recipient_id`` is who
    receives the notification. Both FK to users with ON DELETE CASCADE, so a
    deleted account leaves no dangling notifications. There is no real FK to the
    polymorphic target (``target_type`` / ``target_id``) — same convention as
    ratings/library — integrity is the application's responsibility.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recipient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('new_follower', 'review_like', 'user_completed')",
            name="ck_notifications_type",
        ),
        # Feed query is "recipient's notifications, newest first" — a composite
        # index with created_at DESC serves both the WHERE and the ORDER BY.
        Index(
            "idx_notifications_recipient_created",
            "recipient_id",
            text("created_at DESC"),
        ),
    )
