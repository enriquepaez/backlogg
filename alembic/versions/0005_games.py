"""games — game_genres, games, game_genres_join, game_platforms, game_platforms_join,
companies, company_credits

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── game_genres ───────────────────────────────────────────────
    op.create_table(
        "game_genres",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_game_genre_name"),
        sa.UniqueConstraint("slug", name="uq_game_genre_slug"),
    )

    # ── games ─────────────────────────────────────────────────────
    op.create_table(
        "games",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("original_title", sa.String(length=500), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("game_type", sa.String(length=30), nullable=False),
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
        sa.UniqueConstraint("slug", name="uq_games_slug"),
    )
    op.create_index("idx_games_release_date", "games", ["release_date"])
    op.create_index("idx_games_game_type", "games", ["game_type"])
    op.create_index("idx_games_last_synced_at", "games", ["last_synced_at"])

    # ── trigger for games ─────────────────────────────────────────
    op.execute(
        """
        CREATE TRIGGER set_updated_at_games
        BEFORE UPDATE ON games
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )

    # ── game_genres_join ──────────────────────────────────────────
    op.create_table(
        "game_genres_join",
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "genre_id",
            sa.BigInteger(),
            sa.ForeignKey("game_genres.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
    )
    op.create_index("idx_game_genres_join_genre_id", "game_genres_join", ["genre_id"])

    # ── game_platforms ────────────────────────────────────────────
    op.create_table(
        "game_platforms",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_game_platform_name"),
        sa.UniqueConstraint("slug", name="uq_game_platform_slug"),
    )

    # ── game_platforms_join ───────────────────────────────────────
    op.create_table(
        "game_platforms_join",
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "platform_id",
            sa.BigInteger(),
            sa.ForeignKey("game_platforms.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
    )
    op.create_index("idx_game_platforms_join_platform_id", "game_platforms_join", ["platform_id"])

    # ── companies ─────────────────────────────────────────────────
    op.create_table(
        "companies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("logo_url", sa.String(length=1000), nullable=True),
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
        sa.UniqueConstraint("slug", name="uq_companies_slug"),
    )
    op.create_index(
        "idx_companies_name",
        "companies",
        [sa.text("to_tsvector('simple', name)")],
        postgresql_using="gin",
    )

    # ── trigger for companies ─────────────────────────────────────
    op.execute(
        """
        CREATE TRIGGER set_updated_at_companies
        BEFORE UPDATE ON companies
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )

    # ── company_credits ───────────────────────────────────────────
    op.create_table(
        "company_credits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_type", "item_id", "company_id", "role", name="uq_company_credit"),
    )
    op.create_index("idx_company_credits_company", "company_credits", ["company_id"])
    op.create_index("idx_company_credits_item", "company_credits", ["item_type", "item_id"])


def downgrade() -> None:
    op.drop_index("idx_company_credits_item", table_name="company_credits")
    op.drop_index("idx_company_credits_company", table_name="company_credits")
    op.drop_table("company_credits")
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_companies ON companies;")
    op.drop_index("idx_companies_name", table_name="companies")
    op.drop_table("companies")
    op.drop_index("idx_game_platforms_join_platform_id", table_name="game_platforms_join")
    op.drop_table("game_platforms_join")
    op.drop_table("game_platforms")
    op.drop_index("idx_game_genres_join_genre_id", table_name="game_genres_join")
    op.drop_table("game_genres_join")
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_games ON games;")
    op.drop_index("idx_games_last_synced_at", table_name="games")
    op.drop_index("idx_games_game_type", table_name="games")
    op.drop_index("idx_games_release_date", table_name="games")
    op.drop_table("games")
    op.drop_table("game_genres")
