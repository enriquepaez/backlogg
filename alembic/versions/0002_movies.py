"""movies — movie_genres, movies, movie_genres_join

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── movie_genres ──────────────────────────────────────────────
    op.create_table(
        "movie_genres",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_movie_genre_name"),
        sa.UniqueConstraint("slug", name="uq_movie_genre_slug"),
    )

    # ── movies ────────────────────────────────────────────────────
    op.create_table(
        "movies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("original_title", sa.String(length=500), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("original_language", sa.String(length=10), nullable=True),
        sa.Column("poster_url", sa.String(length=1000), nullable=True),
        sa.Column("backdrop_url", sa.String(length=1000), nullable=True),
        sa.Column("budget", sa.BigInteger(), nullable=True),
        sa.Column("revenue", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("rating_external", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("rating_count_external", sa.Integer(), nullable=True),
        sa.Column("rating_internal", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column(
            "rating_count_internal",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_movies_slug"),
    )
    op.create_index("idx_movies_release_date", "movies", ["release_date"])
    op.create_index("idx_movies_last_synced_at", "movies", ["last_synced_at"])

    # ── trigger for movies ────────────────────────────────────────
    op.execute(
        """
        CREATE TRIGGER set_updated_at_movies
        BEFORE UPDATE ON movies
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )

    # ── movie_genres_join ─────────────────────────────────────────
    op.create_table(
        "movie_genres_join",
        sa.Column(
            "movie_id",
            sa.BigInteger(),
            sa.ForeignKey("movies.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "genre_id",
            sa.BigInteger(),
            sa.ForeignKey("movie_genres.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
    )
    op.create_index("idx_movie_genres_join_genre_id", "movie_genres_join", ["genre_id"])


def downgrade() -> None:
    op.drop_index("idx_movie_genres_join_genre_id", table_name="movie_genres_join")
    op.drop_table("movie_genres_join")
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_movies ON movies;")
    op.drop_index("idx_movies_last_synced_at", table_name="movies")
    op.drop_index("idx_movies_release_date", table_name="movies")
    op.drop_table("movies")
    op.drop_table("movie_genres")
