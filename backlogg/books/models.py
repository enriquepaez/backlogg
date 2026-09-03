from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backlogg.core.database import Base

# Association table for the many-to-many between books and genres
book_genres_join = Table(
    "book_genres_join",
    Base.metadata,
    Column(
        "book_id",
        BigInteger,
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    ),
    Column(
        "genre_id",
        BigInteger,
        ForeignKey("book_genres.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    ),
    Index("idx_book_genres_join_genre_id", "genre_id"),
)


class BookGenre(Base):
    __tablename__ = "book_genres"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    books: Mapped[list["Book"]] = relationship(
        "Book", secondary=book_genres_join, back_populates="genres"
    )

    __table_args__ = (UniqueConstraint("name", name="uq_book_genre_name"),)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    original_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_publish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    original_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Feature 71 (book_isbn_field): first ISBN reported by Open Library's
    # search.json for this work — see book_to_dict for the tie-break when
    # several are returned.
    isbn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rating_external: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    rating_count_external: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_internal: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count_internal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Feature 49 (catalog_manual_edit): column names manually edited via the
    # admin backoffice (PATCH /v1/admin/book/{slug}). The nightly sync skips
    # any column listed here instead of overwriting the admin's edit — see
    # upsert_book below.
    locked_fields: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Feature 85 (backfill_credits_targeted): when the targeted credits
    # backfill last completed a successful credits lookup for this row.
    # NULL = never looked up. Stamped even when the source returned no
    # credits, so items that legitimately have none are not retried forever.
    credits_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    genres: Mapped[list[BookGenre]] = relationship(
        "BookGenre", secondary=book_genres_join, back_populates="books"
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_books_slug"),
        Index("idx_books_first_publish_date", "first_publish_date"),
        Index("idx_books_last_synced_at", "last_synced_at"),
    )
