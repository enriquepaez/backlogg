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

__all__ = ["LibraryEntry", "LIBRARY_STATUSES"]

# Allowed backlog statuses. Stored as a plain string + CHECK constraint, the
# same way the project models other enum-like columns (games.game_type,
# user_ratings score range) — no PostgreSQL ENUM type.
LIBRARY_STATUSES = ("want", "in_progress", "completed", "dropped")


class LibraryEntry(Base):
    """One row per (user, item): the user's backlog status for that item.

    Polymorphic ``item_type`` + ``item_id`` — same pattern as
    ``backlogg.ratings.models.UserRating`` / ``backlogg.shared.models.Credit``.
    No real FK to movies/series/books/games; integrity is enforced by the
    application layer (backlogg/library/repository.py).
    """

    __tablename__ = "library_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "item_type", "item_id", name="uq_library_entry_item"),
        CheckConstraint(
            "status IN ('want', 'in_progress', 'completed', 'dropped')",
            name="ck_library_entries_status",
        ),
        Index("idx_library_entries_item", "item_type", "item_id"),
        Index("idx_library_entries_user", "user_id"),
        Index("idx_library_entries_user_status", "user_id", "status"),
    )
