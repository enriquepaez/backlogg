from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Column,
    Computed,
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
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backlogg.core.database import Base
from backlogg.shared.search_vector import SEARCH_VECTOR_SQL

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

    # Feature 91 (search_expression_index): full-text vector of this row,
    # maintained by Postgres itself as a STORED generated column and indexed
    # by ``idx_books_search_vector``.  It replaces the ``catalog_search``
    # materialized view, whose ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` no
    # longer fit in Neon's 512 MB (issue #28) — a generated column is
    # recomputed inside the writing statement, so there is nothing left to
    # refresh.  The expression is shared by all four content tables, see
    # ``backlogg/shared/search_vector.py``.
    #
    # ``deferred`` because it is large (~0,7 KB/row) and no Python code ever
    # reads it: it exists to be filtered with ``@@`` and ranked with
    # ``ts_rank`` inside ``backlogg/search/repository.py``.  Without this every
    # ``select(Book)`` in the codebase would drag the vector along.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_VECTOR_SQL, persisted=True),
        nullable=False,
        deferred=True,
    )

    genres: Mapped[list[BookGenre]] = relationship(
        "BookGenre", secondary=book_genres_join, back_populates="books"
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_books_slug"),
        Index("idx_books_first_publish_date", "first_publish_date"),
        Index("idx_books_last_synced_at", "last_synced_at"),
        Index("idx_books_search_vector", "search_vector", postgresql_using="gin"),
    )
