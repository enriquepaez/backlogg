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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backlogg.core.database import Base

# ── Association tables ────────────────────────────────────────────────────────

game_genres_join = Table(
    "game_genres_join",
    Base.metadata,
    Column(
        "game_id",
        BigInteger,
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    ),
    Column(
        "genre_id",
        BigInteger,
        ForeignKey("game_genres.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    ),
    Index("idx_game_genres_join_genre_id", "genre_id"),
)

game_platforms_join = Table(
    "game_platforms_join",
    Base.metadata,
    Column(
        "game_id",
        BigInteger,
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    ),
    Column(
        "platform_id",
        BigInteger,
        ForeignKey("game_platforms.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    ),
    Index("idx_game_platforms_join_platform_id", "platform_id"),
)


# ── Lookup tables ─────────────────────────────────────────────────────────────


class GameGenre(Base):
    __tablename__ = "game_genres"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    games: Mapped[list["Game"]] = relationship(
        "Game", secondary=game_genres_join, back_populates="genres"
    )

    __table_args__ = (UniqueConstraint("name", name="uq_game_genre_name"),)


class GamePlatform(Base):
    __tablename__ = "game_platforms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    games: Mapped[list["Game"]] = relationship(
        "Game", secondary=game_platforms_join, back_populates="platforms"
    )

    __table_args__ = (UniqueConstraint("name", name="uq_game_platform_name"),)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("slug", name="uq_companies_slug"),)


class CompanyCredit(Base):
    __tablename__ = "company_credits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    company: Mapped[Company] = relationship("Company")

    __table_args__ = (
        UniqueConstraint("item_type", "item_id", "company_id", "role", name="uq_company_credit"),
        Index("idx_company_credits_company", "company_id"),
        Index("idx_company_credits_item", "item_type", "item_id"),
    )


# ── Main model ────────────────────────────────────────────────────────────────


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    original_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    game_type: Mapped[str] = mapped_column(String(30), nullable=False)
    original_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    backdrop_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    rating_external: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    rating_count_external: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_internal: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count_internal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    genres: Mapped[list[GameGenre]] = relationship(
        "GameGenre", secondary=game_genres_join, back_populates="games"
    )
    platforms: Mapped[list[GamePlatform]] = relationship(
        "GamePlatform", secondary=game_platforms_join, back_populates="games"
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_games_slug"),
        Index("idx_games_release_date", "release_date"),
        Index("idx_games_game_type", "game_type"),
        Index("idx_games_last_synced_at", "last_synced_at"),
    )
