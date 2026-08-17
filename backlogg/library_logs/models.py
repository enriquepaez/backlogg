from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

__all__ = ["LibraryLog"]


class LibraryLog(Base):
    """One row per logged session (rewatch/replay/reread) of an item.

    Polymorphic ``item_type`` + ``item_id`` — same pattern as
    ``backlogg.library.models.LibraryEntry`` / ``backlogg.ratings.models.UserRating``,
    but deliberately **without** a ``UniqueConstraint(user_id, item_type, item_id)``:
    a user can log the same item multiple times (e.g. two separate rewatches of
    the same movie, each with its own date), unlike ``LibraryEntry``/``UserRating``
    which are one row per (user, item). Desacoplada de ``user_ratings`` — a log
    has no ``score``/``review_text`` of its own; that keeps living exclusively on
    ``UserRating``. No real FK to movies/series/books/games; integrity is
    enforced by the application layer (``backlogg/library_logs/repository.py``).
    """

    __tablename__ = "library_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    logged_on: Mapped[date] = mapped_column(Date, nullable=False)
    rewatch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_library_logs_item", "item_type", "item_id"),
        Index("idx_library_logs_user", "user_id"),
    )
