from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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

__all__ = ["UserRating", "ReviewLike"]


class UserRating(Base):
    """One row per (user, item): an optional 1-5 score and/or optional review text.

    Polymorphic ``item_type`` + ``item_id`` — same pattern as
    ``backlogg.shared.models.Credit`` / ``backlogg.shared.external_ids.ExternalId``.
    No real FK to movies/series/books/games; integrity is enforced by the
    application layer (backlogg/ratings/repository.py).
    """

    __tablename__ = "user_ratings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "item_type", "item_id", name="uq_user_rating_item"),
        CheckConstraint(
            "score IS NULL OR (score >= 1 AND score <= 5)", name="ck_user_ratings_score_range"
        ),
        Index("idx_user_ratings_item", "item_type", "item_id"),
        Index("idx_user_ratings_user", "user_id"),
    )


class ReviewLike(Base):
    """A like on a UserRating (review). One like per (user, rating)."""

    __tablename__ = "review_likes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_ratings.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "rating_id", name="uq_review_like"),
        Index("idx_review_likes_rating", "rating_id"),
        Index("idx_review_likes_user", "user_id"),
    )
