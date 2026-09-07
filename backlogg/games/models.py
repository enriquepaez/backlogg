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
    # Feature 49 (catalog_manual_edit): column names manually edited via the
    # admin backoffice (PATCH /v1/admin/game/{slug}). The nightly sync skips
    # any column listed here instead of overwriting the admin's edit — see
    # upsert_game below.
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

    # Feature 91 (search_expression_index): full-text vector of this row,
    # maintained by Postgres itself as a STORED generated column and indexed
    # by ``idx_games_search_vector``.  It replaces the ``catalog_search``
    # materialized view, whose ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` no
    # longer fit in Neon's 512 MB (issue #28) — a generated column is
    # recomputed inside the writing statement, so there is nothing left to
    # refresh.  The expression is shared by all four content tables, see
    # ``backlogg/shared/search_vector.py``.
    #
    # ``deferred`` because it is large (~0,7 KB/row) and no Python code ever
    # reads it: it exists to be filtered with ``@@`` and ranked with
    # ``ts_rank`` inside ``backlogg/search/repository.py``.  Without this every
    # ``select(Game)`` in the codebase would drag the vector along.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_VECTOR_SQL, persisted=True),
        nullable=False,
        deferred=True,
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
        Index("idx_games_search_vector", "search_vector", postgresql_using="gin"),
    )
