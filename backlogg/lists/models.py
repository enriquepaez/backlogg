from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

__all__ = ["UserList", "ListItem"]


class UserList(Base):
    """A named, user-owned collection (e.g. 'Best sci-fi').

    One row per list. ``slug`` is derived from the title at creation time and
    never changes (same rule as the content slugs). The DB guarantees
    uniqueness per ``(user_id, slug)``; the application additionally resolves
    slug collisions globally so ``/lists/{slug}`` routes to a single list.
    Visibility is controlled by ``is_public``.
    """

    __tablename__ = "user_lists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_user_list_slug"),
        Index("idx_user_lists_user", "user_id"),
        Index("idx_user_lists_slug", "slug"),
    )


class ListItem(Base):
    """One ordered entry inside a :class:`UserList`.

    Polymorphic ``item_type`` + ``item_id`` — same pattern as
    ``backlogg.library.models.LibraryEntry`` / ``backlogg.ratings.models``.
    No real FK to the content tables; integrity is enforced by the application
    layer (backlogg/lists/repository.py). ``position`` is a 0-based ordering
    index within the owning list; new items are appended at the end.
    """

    __tablename__ = "list_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_lists.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("list_id", "item_type", "item_id", name="uq_list_item"),
        Index("idx_list_items_list", "list_id"),
    )
