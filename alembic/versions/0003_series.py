"""series — series_genres, series, series_genres_join

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── series_genres ─────────────────────────────────────────────
    op.create_table(
        "series_genres",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_series_genre_name"),
        sa.UniqueConstraint("slug", name="uq_series_genre_slug"),
    )

    # ── series ────────────────────────────────────────────────────
    op.create_table(
        "series",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("original_title", sa.String(length=500), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("first_air_date", sa.Date(), nullable=True),
        sa.Column("last_air_date", sa.Date(), nullable=True),
        sa.Column("number_of_seasons", sa.Integer(), nullable=True),
        sa.Column("number_of_episodes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("original_language", sa.String(length=10), nullable=True),
        sa.Column("poster_url", sa.String(length=1000), nullable=True),
        sa.Column("backdrop_url", sa.String(length=1000), nullable=True),
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
        sa.UniqueConstraint("slug", name="uq_series_slug"),
    )
    op.create_index("idx_series_first_air_date", "series", ["first_air_date"])
    op.create_index("idx_series_last_synced_at", "series", ["last_synced_at"])

    # ── trigger for series ────────────────────────────────────────
    op.execute(
        """
        CREATE TRIGGER set_updated_at_series
        BEFORE UPDATE ON series
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )

    # ── series_genres_join ────────────────────────────────────────
    op.create_table(
        "series_genres_join",
        sa.Column(
            "series_id",
            sa.BigInteger(),
            sa.ForeignKey("series.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "genre_id",
            sa.BigInteger(),
            sa.ForeignKey("series_genres.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
    )
    op.create_index("idx_series_genres_join_genre_id", "series_genres_join", ["genre_id"])


def downgrade() -> None:
    op.drop_index("idx_series_genres_join_genre_id", table_name="series_genres_join")
    op.drop_table("series_genres_join")
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_series ON series;")
    op.drop_index("idx_series_last_synced_at", table_name="series")
    op.drop_index("idx_series_first_air_date", table_name="series")
    op.drop_table("series")
    op.drop_table("series_genres")
