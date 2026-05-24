"""books — book_genres, books, book_genres_join

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── book_genres ───────────────────────────────────────────────
    op.create_table(
        "book_genres",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_book_genre_name"),
        sa.UniqueConstraint("slug", name="uq_book_genre_slug"),
    )

    # ── books ──────────────────────────────────────────────────────
    op.create_table(
        "books",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("original_title", sa.String(length=500), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("first_publish_date", sa.Date(), nullable=True),
        sa.Column("original_language", sa.String(length=10), nullable=True),
        sa.Column("poster_url", sa.String(length=1000), nullable=True),
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
        sa.UniqueConstraint("slug", name="uq_books_slug"),
    )
    op.create_index("idx_books_first_publish_date", "books", ["first_publish_date"])
    op.create_index("idx_books_last_synced_at", "books", ["last_synced_at"])

    # ── trigger for books ─────────────────────────────────────────
    op.execute(
        """
        CREATE TRIGGER set_updated_at_books
        BEFORE UPDATE ON books
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )

    # ── book_genres_join ──────────────────────────────────────────
    op.create_table(
        "book_genres_join",
        sa.Column(
            "book_id",
            sa.BigInteger(),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "genre_id",
            sa.BigInteger(),
            sa.ForeignKey("book_genres.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
    )
    op.create_index("idx_book_genres_join_genre_id", "book_genres_join", ["genre_id"])


def downgrade() -> None:
    op.drop_index("idx_book_genres_join_genre_id", table_name="book_genres_join")
    op.drop_table("book_genres_join")
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_books ON books;")
    op.drop_index("idx_books_last_synced_at", table_name="books")
    op.drop_index("idx_books_first_publish_date", table_name="books")
    op.drop_table("books")
    op.drop_table("book_genres")
