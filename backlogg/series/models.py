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

# Association table for the many-to-many between series and genres
series_genres_join = Table(
    "series_genres_join",
    Base.metadata,
    Column(
        "series_id",
        BigInteger,
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    ),
    Column(
        "genre_id",
        BigInteger,
        ForeignKey("series_genres.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    ),
    Index("idx_series_genres_join_genre_id", "genre_id"),
)


class SeriesGenre(Base):
    __tablename__ = "series_genres"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    series: Mapped[list["Series"]] = relationship(
        "Series", secondary=series_genres_join, back_populates="genres"
    )

    __table_args__ = (UniqueConstraint("name", name="uq_series_genre_name"),)


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    original_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_air_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_air_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    number_of_seasons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number_of_episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    original_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    backdrop_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    rating_external: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    rating_count_external: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_internal: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count_internal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Feature 49 (catalog_manual_edit): column names manually edited via the
    # admin backoffice (PATCH /v1/admin/series/{slug}). The nightly sync
    # skips any column listed here instead of overwriting the admin's edit —
    # see upsert_series below.
    locked_fields: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    genres: Mapped[list[SeriesGenre]] = relationship(
        "SeriesGenre", secondary=series_genres_join, back_populates="series"
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_series_slug"),
        Index("idx_series_first_air_date", "first_air_date"),
        Index("idx_series_last_synced_at", "last_synced_at"),
    )
