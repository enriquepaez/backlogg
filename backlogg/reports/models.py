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

__all__ = ["ReviewReport"]


class ReviewReport(Base):
    """A user's report flagging a review (a ``UserRating`` row) as problematic.

    ``rating_id`` points at the reported review — a row in ``user_ratings`` — and
    ``reporter_id`` at the user who filed it. One report per ``(reporter, rating)``
    pair (``uq_review_report_pair``) makes reporting idempotent: reporting the
    same review twice never creates a second row. Both FKs cascade on delete, so
    a report vanishes when either the reporter's account or the review is removed.

    ``reason`` is a short, optional free-text note. ``status`` is an enum-like
    plain string constrained by a CHECK to ``open``/``resolved`` (same modelling
    as ``account_tokens.purpose``); it starts ``open`` and flips to ``resolved``
    with ``resolved_at`` set when an admin clears it from the queue.
    """

    __tablename__ = "review_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reporter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_ratings.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("reporter_id", "rating_id", name="uq_review_report_pair"),
        CheckConstraint("status IN ('open', 'resolved')", name="ck_review_reports_status"),
        Index("idx_review_reports_status", "status"),
    )
