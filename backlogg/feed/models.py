from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

__all__ = ["ActivityEvent", "ACTIVITY_EVENT_TYPES"]

# Event types that can appear in the feed. Plain string + CHECK constraint —
# no PostgreSQL ENUM type, same modelling as library_entries.status /
# user_ratings.score / notifications.type.
ACTIVITY_EVENT_TYPES = ("rating_created", "status_completed")


class ActivityEvent(Base):
    """One row per feed-worthy fact: a rating/review was created or updated
    with content, or a library entry transitioned into ``completed``.

    Generic on purpose (feature 54) — the feed (``backlogg/feed/repository.py``)
    reads exclusively from this table instead of joining ``user_ratings``
    directly, so a future event type only needs a new writer, not a change to
    the feed's read model.

    - ``rating_created``: ``rating_id`` points at the ``user_ratings`` row.
      ``uq_activity_events_rating_id`` guarantees at most one event per rating
      (multiple NULLs are allowed by Postgres unique constraints, so this does
      not constrain ``status_completed`` rows, whose ``rating_id`` is always
      NULL) — this is what makes generation on repeat rating updates
      idempotent (INSERT ... ON CONFLICT DO NOTHING keyed on ``rating_id``).
      Deleting the rating cascades to its event (``ON DELETE CASCADE``).
    - ``status_completed``: ``rating_id`` is NULL. The caller
      (``backlogg/library/service.py``) only inserts one when the library
      entry's status actually transitions *into* ``completed`` — repeating an
      already-``completed`` PUT does not insert another row.

    Polymorphic ``item_type`` + ``item_id`` — same pattern as
    ``user_ratings``/``library_entries``. No real FK to movies/series/books/
    games; integrity is enforced by the application layer.
    """

    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rating_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_ratings.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("rating_id", name="uq_activity_events_rating_id"),
        CheckConstraint(
            "event_type IN ('rating_created', 'status_completed')",
            name="ck_activity_events_type",
        ),
        Index("idx_activity_events_user", "user_id", "created_at"),
        Index("idx_activity_events_item", "item_type", "item_id"),
    )
